# Copyright (C) 2015 East Asian Observatory
# All Rights Reserved.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful,but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,51 Franklin
# Street, Fifth Floor, Boston, MA  02110-1301, USA

from __future__ import absolute_import, division, print_function, \
    unicode_literals

from collections import namedtuple

from ...email.format import render_email_template
from ...error import DatabaseIntegrityError, NoSuchRecord, UserError
from ...util import get_countries
from ...view import auth
from ...view.util import with_proposal, with_review, with_verified_admin
from ...web.util import ErrorPage, \
    HTTPError, HTTPForbidden, HTTPNotFound, HTTPRedirect, \
    flash, session, url_for
from ...type import Assessment, FormatType, GroupType, Link, MemberPIInfo, \
    ProposalState, ProposalWithCode, ReviewerRole, TextRole, \
    null_tuple

ProposalWithReviewerPersons = namedtuple(
    'ProposalWithReviewerPersons',
    ProposalWithCode._fields + ('person_ids_primary', 'person_ids_secondary'))


class GenericReview(object):
    @with_verified_admin
    def view_review_call_reviewers(self, db, call_id):
        try:
            call = db.get_call(facility_id=self.id_, call_id=call_id)
        except NoSuchRecord:
            raise HTTPNotFound('Call or semester not found')

        proposals = db.search_proposal(
            call_id=call_id, state=ProposalState.submitted_states(),
            person_pi=True, with_reviewers=True, with_review_info=True)

        return {
            'title': 'Reviewers: {} {}'.format(call.semester_name,
                                               call.queue_name),
            'proposals': [
                ProposalWithCode(*x, code=self.make_proposal_code(db, x),
                                 facility_code=None)
                for x in proposals.values()],
            'targets': [
                Link('Assign technical reviewers',
                     url_for('.review_call_technical', call_id=call_id)),
                Link('Assign committee members',
                     url_for('.review_call_committee', call_id=call_id))],
        }

    @with_verified_admin
    def view_reviewer_grid(self, db, call_id, primary_role, form):
        try:
            call = db.get_call(facility_id=self.id_, call_id=call_id)
        except NoSuchRecord:
            raise HTTPNotFound('Call or semester not found')

        if primary_role == ReviewerRole.TECH:
            group_type = GroupType.TECH
            secondary_role = None
            target = url_for('.review_call_technical', call_id=call_id)

        elif primary_role == ReviewerRole.CTTEE_PRIMARY:
            group_type = GroupType.CTTEE
            secondary_role = ReviewerRole.CTTEE_SECONDARY
            target = url_for('.review_call_committee', call_id=call_id)

        else:
            raise ErrorPage('Unexpected reviewer role')

        primary_role_info = ReviewerRole.get_info(primary_role)
        secondary_role_info = (None if secondary_role is None else
                               ReviewerRole.get_info(secondary_role))

        group_info = GroupType.get_info(group_type)

        group_members = db.search_group_member(queue_id=call.queue_id,
                                               group_type=group_type,
                                               with_person=True)

        group_person_ids = [x.person_id for x in group_members.values()]

        # Set of proposals and person identifiers to use to avoid allocating
        # someone the review of their own proposal.
        proposal_members = set()

        proposals = []
        for proposal in db.search_proposal(
                call_id=call_id, state=ProposalState.submitted_states(),
                with_members=True, with_reviewers=True).values():

            for member in proposal.members.values():
                proposal_members.add((proposal.id, member.person_id))

            try:
                proposal_pi = proposal.members.get_pi()
            except KeyError:
                proposal_pi = null_tuple(MemberPIInfo)

            # Emulate search_proposal(person_pi=True) behaviour by setting
            # the "members" attribute to just the PI.
            proposal = proposal._replace(members=proposal_pi)

            proposals.append(ProposalWithReviewerPersons(
                *proposal, code=self.make_proposal_code(db, proposal),
                facility_code=None,
                person_ids_primary=(
                    proposal.reviewers.person_id_by_role(primary_role)),
                person_ids_secondary=(
                    None if secondary_role is None else
                    proposal.reviewers.person_id_by_role(secondary_role))))

        role_list = zip([primary_role, secondary_role],
                        [primary_role_info, secondary_role_info],
                        ['primary', 'secondary'])

        message = None

        if form is not None:
            # Read the form inputs into an updated proposal list.  Do this
            # first so that we can return the whole updated grid to the user
            # in case of an error performing the update.
            proposals_updated = []
            for proposal in proposals:
                for (role, role_info, prefix) in role_list:
                    if role is None:
                        continue

                    if role_info.unique:
                        # Read the radio button setting.
                        person_ids = []
                        id_ = '{}_{}'.format(prefix, proposal.id)
                        if id_ in form:
                            person_id = int(form[id_])
                            if person_id in group_person_ids:
                                person_ids = [person_id]

                    else:
                        # See which checkbox inputs are present.
                        person_ids = [
                            x for x in group_person_ids
                            if '{}_{}_{}'.format(prefix, proposal.id, x)
                            in form]

                    proposal = proposal._replace(
                        **{'person_ids_{}'.format(prefix): person_ids})

                proposals_updated.append(proposal)

            try:
                reviewer_remove = []
                reviewer_add = []

                for (proposal, proposal_updated) in zip(
                        proposals, proposals_updated):
                    for (role, role_info, prefix) in role_list:
                        if role is None:
                            continue
                        if proposal.id != proposal_updated.id:
                            raise HTTPError('Proposals got out of sync.')

                        id_ = 'person_ids_{}'.format(prefix)
                        orig = getattr(proposal, id_)
                        updated = getattr(proposal_updated, id_)

                        # Apply uniqueness constraint.
                        if role_info.unique and (len(updated) > 1):
                            raise UserError(
                                'Multiple {} reviewers selected for '
                                'proposal {}.',
                                prefix, proposal.code)

                        for person_id in updated:
                            if person_id in orig:
                                orig.remove(person_id)
                            else:
                                if ((proposal.id, person_id)
                                        in proposal_members):
                                    raise UserError(
                                        'A proposal member has been selected '
                                        'as a reviewer for proposal {}.',
                                        proposal.code)

                                reviewer_add.append({
                                    'proposal_id': proposal.id,
                                    'person_id': person_id,
                                    'role': role,
                                })

                        for person_id in orig:
                            reviewer_remove.append({
                                'proposal_id': proposal.id,
                                'person_id': person_id,
                                'role': role,
                            })

                try:
                    db.multiple_reviewer_update(
                        remove=reviewer_remove, add=reviewer_add)
                except DatabaseIntegrityError:
                    raise UserError(
                        'Could not update reviewer assignments. '
                        'Perhaps you are trying to remove a reviewer '
                        'who already provided a review?')

                flash('The {} assignments have been updated.',
                      group_info.name.lower())
                raise HTTPRedirect(url_for('.review_call_reviewers',
                                           call_id=call_id))

            except UserError as e:
                message = e.message
                proposals = proposals_updated

        return {
            'title': '{}: {} {}'.format(group_info.name.title(),
                                        call.semester_name, call.queue_name),
            'proposals': proposals,
            'target': target,
            'group_members': list(group_members.values()),
            'primary_unique': primary_role_info.unique,
            'secondary_unique': (None if secondary_role_info is None else
                                 secondary_role_info.unique),
            'message': message,
            'proposal_members': proposal_members,
        }

    @with_verified_admin
    @with_proposal(permission='none')
    def view_reviewer_add(self, db, proposal, proposal_can, role, form):
        try:
            role_info = ReviewerRole.get_info(role)
        except KeyError:
            raise HTTPError('Unknown reviewer role')

        if not ProposalState.is_submitted(proposal.state):
            raise ErrorPage('This proposal is not in a submitted state.')

        proposal_person_ids = [
            x.person_id for x in proposal.members.values()
        ]

        existing_person_ids = [
            x.person_id for x in db.search_reviewer(
                proposal_id=proposal.id, role=role).values()
        ]

        message_link = None
        message_invite = None

        member = dict(person_id=None, name='', email='')

        if form is not None:
            if 'person_id' in form:
                member['person_id'] = int(form['person_id'])
            member['name'] = form.get('name', '')
            member['email'] = form.get('email', '')

            proposal_code = self.make_proposal_code(db, proposal)

            email_ctx = {
                'proposal': proposal,
                'proposal_code': proposal_code,
                'role_info': role_info,
                'inviter_name': session['person']['name'],
                'target_proposal': url_for(
                    '.proposal_view', proposal_id=proposal.id, _external=True),
            }

            if 'submit_link' in form:
                try:
                    if member['person_id'] is None:
                        raise UserError(
                            'No-one was selected from the directory.')
                    try:
                        person = db.get_person(person_id=member['person_id'])
                    except NoSuchRecord:
                        raise UserError('Could not find the person profile.')

                    if person.id in proposal_person_ids:
                        raise UserError(
                            'This person is a member of the proposal.')

                    if person.id in existing_person_ids:
                        raise UserError(
                            'This person already has this role.')

                    reviewer_id = db.add_reviewer(
                        proposal_id=proposal.id,
                        person_id=person.id, role=role)

                    email_ctx.update({
                        'recipient_name': person.name,
                        'target_review': url_for(
                            '.review_edit',
                            reviewer_id=reviewer_id, _external=True),
                    })

                    db.add_message(
                        'Proposal {} review'.format(proposal_code),
                        render_email_template('review_invitation.txt',
                                              email_ctx, facility=self),
                        [person.id])

                    flash('{} has been added as a reviewer.', person.name)

                    raise HTTPRedirect(url_for(
                        '.review_call_reviewers', call_id=proposal.call_id))

                except UserError as e:
                    message_link = e.message

            elif 'submit_invite' in form:
                try:
                    if not member['name']:
                        raise UserError('Please enter the person\'s name.')
                    if not member['email']:
                        raise UserError('Please enter an email address.')

                    person_id = db.add_person(member['name'])
                    db.add_email(person_id, member['email'], primary=True)
                    reviewer_id = db.add_reviewer(
                        proposal_id=proposal.id,
                        person_id=person_id, role=role)
                    (token, expiry) = db.add_invitation(person_id)

                    email_ctx.update({
                        'token': token,
                        'expiry': expiry,
                        'recipient_name': member['name'],
                        'target_review': url_for(
                            '.review_edit',
                            reviewer_id=reviewer_id, _external=True),
                        'target_url': url_for(
                            'people.invitation_token_enter',
                            token=token, _external=True),
                        'target_plain': url_for(
                            'people.invitation_token_enter',
                            _external=True),
                    })

                    db.add_message(
                        'Proposal {} review'.format(proposal_code),
                        render_email_template('review_invitation.txt',
                                              email_ctx, facility=self),
                        [person_id])

                    flash('{} has been invited to register.', member['name'])

                    # Return to the call reviewers page after editing the new
                    # reviewer's institution.
                    session['next_page'] = url_for(
                        '.review_call_reviewers', call_id=proposal.call_id)

                    raise HTTPRedirect(url_for(
                        'people.person_edit_institution', person_id=person_id))

                except UserError as e:
                    message_invite = e.message

            else:
                raise ErrorPage('Unknown action.')

        # Prepare list of people to display as the registered member directory.
        cs = get_countries()
        exclude_person_ids = proposal_person_ids + existing_person_ids
        persons = [
            p._replace(institution_country=cs.get(p.institution_country))
            for p in db.search_person(registered=True, public=True,
                                      with_institution=True).values()
            if p.id not in exclude_person_ids]

        if role == ReviewerRole.EXTERNAL:
            target = url_for('.review_external_add', proposal_id=proposal.id)
        else:
            raise HTTPError('Unexpected reviewer role.')

        return {
            'title': 'Add {} Reviewer'.format(role_info.name.title()),
            'persons': persons,
            'member': member,
            'message_link': message_link,
            'message_invite': message_invite,
            'target': target,
            'title_link': 'Select Reviewer from the Directory',
            'title_invite': 'Invite a Reviewer to Register',
            'submit_link': 'Select reviewer',
            'submit_invite': 'Invite to register',
            'label_link': 'Reviewer',
            'navigation': [],
        }

    @with_review(permission='edit')
    def view_review_edit(self, db, reviewer, proposal, can, form,
                         referrer=None):
        try:
            role_info = ReviewerRole.get_info(reviewer.role)
        except KeyError:
            raise HTTPError('Unknown reviewer role')

        message = None

        if form is not None:
            try:
                # Read form inputs first.
                referrer = form.get('referrer', None)

                if role_info.text:
                    reviewer = reviewer._replace(
                        review_text=form['text'],
                        review_format=FormatType.PLAIN)

                if role_info.assessment:
                    try:
                        reviewer = reviewer._replace(
                            review_assessment=int(form['assessment']))
                    except:
                        raise UserError('Please select an assessment.')

                if role_info.rating:
                    try:
                        reviewer = reviewer._replace(
                            review_rating=int(form['rating']))
                    except:
                        raise UserError('Please provide an integer rating.')

                if role_info.weight:
                    try:
                        reviewer = reviewer._replace(
                            review_weight=int(form['weight']))
                    except:
                        raise UserError('Please provide an integer '
                                        'self-assessment weighting.')

                # Validate the form inputs.
                if role_info.assessment:
                    if not Assessment.is_valid(reviewer.review_assessment):
                        raise UserError('Selected assessment not recognized.')

                if role_info.rating:
                    if not (0 <= reviewer.review_rating <= 100):
                        raise UserError('Please give a rating between '
                                        '0 and 100.')

                if role_info.weight:
                    if not (0 <= reviewer.review_weight <= 100):
                        raise UserError('Please give a self-assessment '
                                        'weighting between 0 and 100.')

                db.set_review(
                    reviewer_id=reviewer.id,
                    text=reviewer.review_text,
                    format_=reviewer.review_format,
                    assessment=reviewer.review_assessment,
                    rating=reviewer.review_rating,
                    weight=reviewer.review_weight,
                    is_update=reviewer.review_present)

                flash('The review has been saved.')

                raise HTTPRedirect(referrer if referrer
                                   else url_for('person_reviews'))

            except UserError as e:
                message = e.message

        return {
            'title': 'Edit Review',
            'proposal_code': self.make_proposal_code(db, proposal),
            'proposal': proposal,
            'reviewer': reviewer,
            'role_info': role_info,
            'assessment_options': Assessment.get_options(),
            'message': message,
            'referrer': referrer,
        }

    def view_proposal_reviews(self, db, proposal_id):
        try:
            proposal = db.get_proposal(self.id_, proposal_id,
                                       with_members=True)
        except NoSuchRecord:
            raise HTTPNotFound('Proposal record not found')

        can = auth.for_review(db, reviewer=None, proposal=proposal)

        if not can.view:
            raise HTTPForbidden(
                'Permission denied for this proposal\'s reviews.')

        proposal_code = self.make_proposal_code(db, proposal)

        try:
            abstract = db.get_proposal_text(proposal.id, TextRole.ABSTRACT)
        except NoSuchRecord:
            abstract = None

        reviews = db.search_reviewer(proposal_id=proposal.id, with_review=True,
                                     with_review_text=True)

        return {
            'title': '{}: Reviews'.format(proposal_code),
            'proposal': proposal,
            'proposal_code': proposal_code,
            'abstract': abstract,
            'categories': db.search_proposal_category(
                proposal_id=proposal.id).values(),
            'reviews': reviews.values(),
            'can_edit': can.edit,
        }