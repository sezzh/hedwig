# Copyright (C) 2015-2016 East Asian Observatory
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

from collections import defaultdict, namedtuple, OrderedDict
from itertools import count, izip
import re
from urllib import urlencode

from ...error import NoSuchRecord, NoSuchValue, UserError
from ...web.util import HTTPRedirect, flash, url_for
from ...view.util import organise_collection, with_call_review, with_proposal
from ...type.collection import ResultTable
from ...type.enum import AffiliationType, FormatType, \
    PermissionType, ProposalState
from ...type.simple import Link, RouteInfo, ValidationMessage
from ...type.util import null_tuple
from ..generic.view import Generic
from .calculator_heterodyne import HeterodyneCalculator
from .calculator_scuba2 import SCUBA2Calculator
from .type import \
    JCMTAvailable, JCMTAvailableCollection, JCMTAncillary, \
    JCMTCallType, JCMTInstrument, JCMTOptionValue, JCMTOptions, \
    JCMTRequest, JCMTRequestCollection, JCMTRequestTotal, \
    JCMTReview, JCMTReviewerExpertise, JCMTReviewerRole, \
    JCMTReviewRatingJustification, JCMTReviewRatingTechnical, \
    JCMTReviewRatingUrgency, \
    JCMTTextRole, \
    JCMTWeather


class JCMT(Generic):
    cadc_advanced_search = \
        'http://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/search/'

    omp_cgi_bin = 'http://omp.eao.hawaii.edu/cgi-bin/'

    @classmethod
    def get_code(cls):
        return 'jcmt'

    def get_name(self):
        return 'JCMT'

    def get_call_types(self):
        return JCMTCallType

    def get_text_roles(self):
        return JCMTTextRole

    def get_reviewer_roles(self):
        return JCMTReviewerRole

    def get_custom_filters(self):
        def expertise_name(value):
            try:
                return JCMTReviewerExpertise.get_name(value)
            except KeyError:
                return 'Unknown expertise'

        def review_rating_justification(value):
            try:
                return JCMTReviewRatingJustification.get_name(value)
            except KeyError:
                return 'Unknown justification rating'

        def review_rating_technical(value):
            try:
                return JCMTReviewRatingTechnical.get_name(value)
            except KeyError:
                return 'Unknown technical rating'

        def review_rating_urgency(value):
            try:
                return JCMTReviewRatingUrgency.get_name(value)
            except KeyError:
                return 'Unknown urgency rating'

        return [v for (k, v) in locals().items() if k != 'self']

    def get_custom_routes(self):
        return [
            RouteInfo(
                'pr_summary_edit.html',
                '/proposal/<int:proposal_id>/pr_summary',
                'pr_summary_edit',
                self.view_pr_summary_edit,
                {'allow_post': True, 'init_route_params': ['proposal_id']}),
        ]

    def get_proposal_order(self):
        """
        Get a list of proposal sections in the order in which they should
        be shown.
        """

        return [
            'proposal_summary',
            'proposal_abstract',
            'science_case',
            'proposal_members',
            'proposal_request',
            'proposal_targets',
            'proposal_calculations',
            'technical_case',
            'proposal_previous',
        ]

    def make_proposal_code(self, db, proposal):
        type_class = self.get_call_types()
        type_code = type_class.get_code(proposal.call_type)

        return '{}{}{}{:03d}'.format(
            type_code, proposal.semester_code,
            proposal.queue_code, proposal.number
        ).upper()

    def _parse_proposal_code(self, proposal_code):
        """
        Perform the parsing step of processing a proposal code.

        This splits the code into the semester code, queue code
        and proposal number.
        """

        type_class = self.get_call_types()

        try:
            m = re.match('([A-Z])(\d\d[ABXYZW])([A-Z])(\d\d\d)', proposal_code)

            if not m:
                raise NoSuchRecord(
                    'Proposal code did not match expected pattern')

            (call_type, semester_code, queue_code,
                proposal_number) = m.groups()

            return (semester_code, queue_code, type_class.by_code(call_type),
                    int(proposal_number))

        except ValueError:
            raise NoSuchRecord('Could not parse proposal number ')

        except NoSuchValue:
            raise NoSuchRecord('Did not recognise call type code')

    def get_calculator_classes(self):
        return (SCUBA2Calculator, HeterodyneCalculator)

    def make_archive_search_url(self, ra_deg, dec_deg):
        """
        Make an URL to search the JSA at CADC.
        """

        position = '{:.5f} {:.5f}'.format(ra_deg, dec_deg)

        url = (
            self.cadc_advanced_search + '?' +
            urlencode({
                'Observation.collection': 'JCMT',
                'Plane.position.bounds@Shape1Resolver.value': 'ALL',
                'Plane.position.bounds': position,
            }) +
            '#resultTableTab')

        # Advanced Search doesn't seem to like + as part of the coordinates.
        return url.replace('+', '%20')

    def make_proposal_info_urls(self, proposal_code):
        """
        Generate links to the OMP and to CADC for a given proposal code.
        """

        return [
            Link(
                'OMP', self.omp_cgi_bin + 'projecthome.pl?' +
                urlencode({
                    'urlprojid': proposal_code,
                })),
            Link(
                'CADC', self.cadc_advanced_search + '?' +
                urlencode({
                    'Observation.collection': 'JCMT',
                    'Observation.proposal.id': proposal_code,
                }) + '#resultTableTab'),
        ]

    def make_review_guidelines_url(self, role):
        """
        Make an URL for the guidelines page in the included documentation,
        if the role is external.
        """

        role_class = self.get_reviewer_roles()

        if role == role_class.EXTERNAL:
            return url_for('help.review_page', page_name='external_jcmt',
                           _external=True)

        else:
            return super(JCMT, self).make_review_guidelines_url(role)

    def calculate_overall_rating(self, reviews, with_std_dev=False):
        """
        Calculate the overall rating from a collection of reviewer
        records (including their reviews).
        """

        role_class = self.get_reviewer_roles()

        def rating_weight_function(reviewer):
            role_info = role_class.get_info(reviewer.role)

            if ((not role_info.rating)
                    or (not role_info.jcmt_expertise)
                    or (reviewer.review_rating is None)):
                return (None, None)

            expertise = reviewer.review_extra.expertise

            if expertise is None:
                # TODO: fall back to weight parameter when handling
                # pre-expertise-level reviews?
                return (None, None)

            weight = JCMTReviewerExpertise.get_weight(expertise) / 100.0

            return (reviewer.review_rating, weight)

        return reviews.get_overall_rating(rating_weight_function,
                                          with_std_dev=with_std_dev)

    def calculate_affiliation_assignment(self, db, members, affiliations):
        """
        Calculate the fractional affiliation assignment for the members
        of a proposal.

        This acts like the Generic method which it overrides but applies
        the JCMT affiliation assignment rules.
        """

        affiliation_count = defaultdict(float)
        affiliation_total = 0.0

        # Determine total and maximum affiliation weight.
        total_weight = 0.0
        max_weight = 0.0
        affiliation_weight = {}
        for affiliation in affiliations.values():
            if ((affiliation.type == AffiliationType.EXCLUDED) or
                    (affiliation.type == AffiliationType.SHARED) or
                    (affiliation.weight is None)):
                continue

            total_weight += affiliation.weight

            if affiliation.weight > max_weight:
                max_weight = affiliation.weight

            affiliation_weight[affiliation.id] = affiliation.weight

        # Determine affiliation fractions, in case there are any proposal
        # members with shared affiliation.
        affiliation_fraction = {k: v / total_weight
                                for (k, v) in affiliation_weight.items()}

        # Find the PI (if present) and their affiliation.
        try:
            pi = members.get_pi()
            pi_affiliation = pi.affiliation_id

            # Ensure the PI has a "valid" affiliation as we will use it for
            # excluded-affiliation members.
            if ((pi_affiliation is None) or
                    (pi_affiliation not in affiliations) or
                    (affiliations[pi_affiliation].type ==
                        AffiliationType.EXCLUDED)):
                pi_affiliation = 0

            elif affiliations[pi_affiliation].type == AffiliationType.SHARED:
                # Use special value "None" for shared affiliation (not to be
                # confused with "0" meaning unknown).
                pi_affiliation = None

        except KeyError:
            # KeyError is raised if MemberCollection.get_pi fails to find a
            # PI: record that there is no PI and their affiliation is therefore
            # unknown (represented by "0").
            pi = None
            pi_affiliation = 0

        # Add up weighted affiliation counts for non-PI members.
        for member in members.values():
            # Skip the PI as we will process their affiliation separately.
            if (pi is not None) and (member.id == pi.id):
                continue

            affiliation = member.affiliation_id
            if (affiliation is None) or (affiliation not in affiliations):
                affiliation = 0
            elif affiliations[affiliation].type == AffiliationType.EXCLUDED:
                # Members with excluded affiliations count as the PI's
                # affiliation.
                affiliation = pi_affiliation
            elif affiliations[affiliation].type == AffiliationType.SHARED:
                # Count type "SHARED" as if it were "EXCLUDED" for non-PIs.
                affiliation = pi_affiliation

            if affiliation is None:
                # Affiliation is shared -- this will not happen directly but
                # the member may have "inherited" the PIs's shared affiliation.
                for (aff_id, aff_frac) in affiliation_fraction.items():
                    affiliation_count[aff_id] += aff_frac * max_weight

                affiliation_total += max_weight

            else:
                # Non-shared affiliation -- determine weighting factor to use.
                if affiliation == 0:
                    # Weight "unknown" as the maximum of all the other
                    # weights. In practise there should never be any members
                    # in this state.
                    weight = max_weight
                else:
                    weight = affiliations[affiliation].weight
                    if weight is None:
                        weight = 0.0

                affiliation_count[affiliation] += weight
                affiliation_total += weight

        if not affiliation_total:
            # We didn't find any non-PI members (or they had zero weight),
            # so set the PI weight to 1.0.  Otherwise prepare to add the PI
            # affiliation at the same total weight.  But if there is also
            # no PI, return 100% unknown.
            if pi is None:
                return {0: 1.0}

            pi_weight = 1.0

        else:
            pi_weight = affiliation_total

        if pi is not None:
            # 50% of the assigment is supposed to be apportioned to the PI
            # affiliation, so add the PI with the same weight as all the other
            # members combined.
            if pi_affiliation is None:
                # Affiliation is shared -- assign by affiliation fractions
                # multiplied by the PI's weighting factor.
                for (aff_id, aff_frac) in affiliation_fraction.items():
                    affiliation_count[aff_id] += pi_weight * aff_frac
            else:
                affiliation_count[pi_affiliation] += pi_weight

            affiliation_total += pi_weight

        return {k: (v / affiliation_total)
                for (k, v) in affiliation_count.items()}

    def _view_proposal_extra(self, db, proposal):
        role_class = self.get_text_roles()
        ctx = super(JCMT, self)._view_proposal_extra(
            db, proposal,
            extra_text_roles={'jcmt_pr_summary': role_class.PR_SUMMARY})

        requests = db.search_jcmt_request(proposal_id=proposal.id)

        option_values = db.get_jcmt_options(proposal_id=proposal.id)

        ctx.update({
            'requests': requests.to_table(),
            'jcmt_options': self._get_option_names(option_values),
            'jcmt_option_values': option_values,
        })

        return ctx

    def _get_option_names(self, option_values):
        options = []

        if option_values is not None:
            for (option, option_name) in JCMTOptionValue.get_options(
                    include_unavailable=True).items():
                if getattr(option_values, option):
                    options.append(option_name)

        return options

    def _view_proposal_feedback_extra(self, db, proposal, can):
        ctx = super(JCMT, self)._view_proposal_feedback_extra(
            db, proposal, can)

        if proposal.state == ProposalState.ACCEPTED:
            allocations = db.search_jcmt_allocation(
                proposal_id=proposal.id).to_table()
        else:
            allocations = null_tuple(ResultTable)

        ctx.update({
            'jcmt_allocations': allocations,
        })

        return ctx

    def _validate_proposal_extra(self, db, proposal, extra):
        messages = []

        if extra['jcmt_pr_summary'] is None:
            messages.append(ValidationMessage(
                False,
                'The proposal does not have a public summary.',
                'Edit the public summary',
                url_for('.pr_summary_edit', proposal_id=proposal.id)))

        if not extra['requests'].table:
            messages.append(ValidationMessage(
                True,
                'No observing time has been requested.',
                'Edit the observing request',
                url_for('.request_edit', proposal_id=proposal.id)))

        skip_missing_targets = False
        if extra['jcmt_option_values'] is not None:
            skip_missing_targets = extra['jcmt_option_values'].target_of_opp

        messages.extend(super(JCMT, self)._validate_proposal_extra(
            db, proposal, extra, skip_missing_targets=skip_missing_targets,
            check_excluded_pi=True))

        return messages

    def _get_proposal_tabulation(self, db, call, can, with_extra=False):
        tabulation = super(JCMT, self)._get_proposal_tabulation(
            db, call, can, with_extra)

        exempt = JCMTRequestTotal(total=0.0, weather=defaultdict(float),
                                  instrument=defaultdict(float),
                                  total_non_free=None)
        accepted = JCMTRequestTotal(total=0.0, weather=defaultdict(float),
                                    instrument=defaultdict(float),
                                    total_non_free=None)
        total = JCMTRequestTotal(total=0.0, weather=defaultdict(float),
                                 instrument=defaultdict(float),
                                 total_non_free=None)
        original = JCMTRequestTotal(total=0.0, weather=defaultdict(float),
                                    instrument=defaultdict(float),
                                    total_non_free=None)

        accepted_affiliation = defaultdict(float)
        total_affiliation = defaultdict(float)
        original_affiliation = defaultdict(float)

        affiliation_ids = [x.id for x in tabulation['affiliations']]

        # Make list of proposal_id values and query all JCMT-specific
        # information from the database.
        proposal_ids = [x['id'] for x in tabulation['proposals']]
        jcmt_requests = db.search_jcmt_request(proposal_id=proposal_ids)
        jcmt_allocations = db.search_jcmt_allocation(proposal_id=proposal_ids)
        jcmt_options = None
        if with_extra:
            jcmt_options = db.search_jcmt_options(proposal_id=proposal_ids)

        # Loop through proposals and attach JCMT-specific information.
        for proposal in tabulation['proposals']:
            request = jcmt_requests.subset_by_proposal(
                proposal['id']).get_total()

            proposal['jcmt_request'] = request

            if jcmt_options is not None:
                proposal['jcmt_options'] = self._get_option_names(
                    jcmt_options.get_proposal(proposal['id'], default=None))

            # Read the committee's time allocation, but only if there is one.
            # Since decisions can now be returned to "undecided", we need
            # to search for allocations regardless of decision presence.
            allocation = None
            proposal_accepted = proposal['decision_accept']
            proposal_exempt = proposal['decision_exempt']
            allocation_records = jcmt_allocations.subset_by_proposal(
                proposal['id'])
            if allocation_records:
                allocation = allocation_records.get_total()

            proposal['jcmt_allocation'] = allocation
            proposal['jcmt_allocation_different'] = \
                ((allocation is not None) and (allocation != request))

            if proposal_accepted and allocation is not None:
                if proposal_exempt:
                    exempt = exempt._replace(
                        total=(exempt.total + allocation.total))

                accepted = accepted._replace(
                    total=(accepted.total + allocation.total))

            if allocation is not None:
                total = total._replace(total=(total.total + allocation.total))
            else:
                total = total._replace(total=(total.total + request.total))

            original = original._replace(
                total=(original.total + request.total))

            for (weather, time) in request.weather.items():
                original.weather[weather] += time
                if allocation is None:
                    total.weather[weather] += time

            if allocation is not None:
                for (weather, time) in allocation.weather.items():
                    if proposal_accepted:
                        if proposal_exempt:
                            exempt.weather[weather] += time
                        accepted.weather[weather] += time
                    total.weather[weather] += time

            for (instrument, time) in request.instrument.items():
                original.instrument[instrument] += time
                if allocation is None:
                    total.instrument[instrument] += time

            if allocation is not None:
                for (instrument, time) in allocation.instrument.items():
                    if proposal_accepted:
                        if proposal_exempt:
                            exempt.instrument[instrument] += time
                        accepted.instrument[instrument] += time
                    total.instrument[instrument] += time

            proposal_affiliations = proposal['affiliations']
            for affiliation in affiliation_ids:
                fraction = proposal_affiliations.get(affiliation)
                if fraction is None:
                    continue

                original_affiliation[affiliation] += \
                    request.total_non_free * fraction

                if allocation is None:
                    total_affiliation[affiliation] += \
                        request.total_non_free * fraction

                else:
                    total_affiliation[affiliation] += \
                        allocation.total_non_free * fraction

                    if proposal_accepted and not proposal_exempt:
                        accepted_affiliation[affiliation] += \
                            allocation.total_non_free * fraction

        # Fetch the amount of time available and distribute it among the
        # affiliations under the assumption that the affiliation weights
        # are percentages.
        available = db.search_jcmt_available(call_id=call.id).get_total()

        total_weight = 0.0
        available_affiliation = {}

        for affiliation in tabulation['affiliations']:
            if (affiliation.id == 0) or (affiliation.weight is None):
                continue

            total_weight += affiliation.weight
            available_affiliation[affiliation.id] = \
                available.total_non_free * affiliation.weight / 100.0

        # Assign the remaining time to the "Unknown" affiliation.
        available_affiliation[0] = \
            (1.0 - (total_weight / 100.0)) * available.total_non_free

        tabulation.update({
            'jcmt_weathers': JCMTWeather.get_available(),
            'jcmt_instruments': JCMTInstrument.get_options(),
            'jcmt_instruments_ancillary':
                JCMTInstrument.get_options_with_ancillary(),
            'jcmt_ancillary_none': JCMTAncillary.NONE,
            'jcmt_ancillaries': JCMTAncillary.get_options(),
            'jcmt_exempt_total': exempt,
            'jcmt_accepted_total': accepted,
            'jcmt_request_total': total,
            'jcmt_request_original': original,
            'jcmt_available': available,
            'affiliation_accepted': accepted_affiliation,
            'affiliation_available': available_affiliation,
            'affiliation_total': total_affiliation,
            'affiliation_original': original_affiliation,
        })

        return tabulation

    def _get_proposal_tabulation_titles(self, tabulation):
        return (
            super(JCMT, self)._get_proposal_tabulation_titles(tabulation) +
            ['Options', 'Request'] +
            [x.name for x in tabulation['jcmt_weathers'].values()] +
            ['Unknown weather'] +
            [x for x in tabulation['jcmt_instruments_ancillary'].values()] +
            ['Unknown instrument'] +
            ['Allocation'] +
            [x.name for x in tabulation['jcmt_weathers'].values()] +
            ['Unknown weather'] +
            [x for x in tabulation['jcmt_instruments_ancillary'].values()] +
            ['Unknown instrument']
        )

    def _get_proposal_tabulation_rows(self, tabulation):
        weathers = list(tabulation['jcmt_weathers'].keys()) + [None]
        instruments = list(
            tabulation['jcmt_instruments_ancillary'].keys()) + [None]

        for (row, proposal) in izip(
                super(JCMT, self)._get_proposal_tabulation_rows(tabulation),
                tabulation['proposals']):
            request = proposal['jcmt_request']
            allocation = proposal['jcmt_allocation']
            if (allocation is None) or (not proposal['decision_accept']):
                allocation = JCMTRequestTotal(None, {}, {}, {})

            yield (
                row +
                [
                    ', '.join(proposal['jcmt_options']),
                    request.total,
                ] +
                [request.weather.get(x) for x in weathers] +
                [request.instrument.get(x) for x in instruments] +
                [allocation.total] +
                [allocation.weather.get(x) for x in weathers] +
                [allocation.instrument.get(x) for x in instruments]
            )

    @with_proposal(permission=PermissionType.EDIT)
    def view_request_edit(self, db, proposal, can, form):
        message = None

        records = db.search_jcmt_request(proposal_id=proposal.id)
        option_values = db.get_jcmt_options(proposal_id=proposal.id)
        if option_values is None:
            option_values = JCMTOptions(
                proposal.id, *((False,) * (len(JCMTOptions._fields) - 1)))

        if form is not None:
            records = self._read_request_form(proposal, form)

            option_update = {}
            for option in JCMTOptionValue.get_options().keys():
                option_update[option] = 'option_{}'.format(option) in form
            option_values = option_values._replace(**option_update)

            try:
                db.sync_jcmt_proposal_request(proposal.id, records)

                db.set_jcmt_options(**option_values._asdict())

                flash('The observing request has been saved.')

                raise HTTPRedirect(url_for('.proposal_view',
                                           proposal_id=proposal.id,
                                           _anchor='request'))

            except UserError as e:
                message = e.message

        return {
            'title': 'Edit Observing Request',
            'message': message,
            'proposal_id': proposal.id,
            'requests': records.values(),
            'instruments': JCMTInstrument.get_options_with_ancillary(),
            'weathers': JCMTWeather.get_available(),
            'options': JCMTOptionValue.get_options(),
            'option_values': option_values,
            'proposal_code': self.make_proposal_code(db, proposal),
        }

    def _read_request_form(self, proposal, form, skip_blank_time=False):
        """
        Read a set of JCMT observing requests (or time allocations) from
        the form and return as a JCMTRequestCollection object.

        Can optionally skip entries with blank times, rather than leaving
        them as non-floats to cause an error to be raised later.
        """

        # Temporary dictionaries for new records.
        updated_records = {}
        added_records = {}

        for param in form:
            if not param.startswith('time_'):
                continue
            id_ = param[5:]

            if id_.startswith('new_'):
                request_id = int(id_[4:])
                destination = added_records
            else:
                request_id = int(id_)
                destination = updated_records

            request_time = form[param]

            if skip_blank_time and (not request_time):
                continue

            try:
                request_time = float(request_time)
            except ValueError:
                # Ignore parsing error for now so that we can leave
                # whatever the user typed in to form for them to correct.
                pass

            (instrument, ancillary) = form['instrument_' + id_].split('_', 1)

            destination[request_id] = JCMTRequest(
                request_id, proposal.id,
                int(instrument),
                int(ancillary),
                int(form['weather_' + id_]),
                request_time)

        return organise_collection(JCMTRequestCollection,
                                   updated_records, added_records)

    def _view_review_edit_get(self, db, reviewer, proposal, form):
        """
        Read JCMT-specific review form values.
        """

        role_class = self.get_reviewer_roles()
        role_info = role_class.get_info(reviewer.role)

        if reviewer.id is None:
            jcmt_review = null_tuple(JCMTReview)
        else:
            try:
                jcmt_review = db.get_jcmt_review(reviewer.id)
            except NoSuchRecord:
                jcmt_review = null_tuple(JCMTReview)

        if role_info.jcmt_expertise:
            try:
                jcmt_review = jcmt_review._replace(
                    expertise=int(form['jcmt_expertise']))
            except:
                raise UserError('Please select an expertise level.')

        if role_info.jcmt_external:
            # Read text fields.
            jcmt_review = jcmt_review._replace(
                review_aims=form['jcmt_review_aims'],
                review_goals=form['jcmt_review_goals'],
                review_difficulties=form['jcmt_review_difficulties'],
                review_details=form['jcmt_review_details'],
                review_obj_inst=form['jcmt_review_obj_inst'],
                review_telescope=form['jcmt_review_telescope'],
                review_format=FormatType.PLAIN)

            # Read integer fields with try-except to catch parse errors.
            try:
                jcmt_review = jcmt_review._replace(
                    rating_justification=int(
                        form['jcmt_rating_justification']),
                    rating_technical=int(form['jcmt_rating_technical']),
                    rating_urgency=int(form['jcmt_rating_urgency']))
            except:
                raise UserError('Please select a rating from each scale.')

        return jcmt_review

    def _view_review_edit_save(self, db, reviewer, proposal, info):
        """
        Save JCMT-specific review parts.
        """

        role_class = self.get_reviewer_roles()

        db.set_jcmt_review(
            role_class=role_class,
            reviewer_id=reviewer.id,
            review=info,
            is_update=(info.reviewer_id is not None))

    def _view_review_edit_extra(self, db, reviewer, proposal, info):
        if info is None:
            if reviewer.id is None:
                info = null_tuple(JCMTReview)
            else:
                try:
                    info = db.get_jcmt_review(reviewer.id)
                except NoSuchRecord:
                    info = null_tuple(JCMTReview)

            request = None
            allocation = None

            # If this is the feedback review, fetch the request and allocation.
            if reviewer.role == JCMTReviewerRole.FEEDBACK:
                request = db.search_jcmt_request(proposal_id=proposal.id)
                if proposal.decision_accept:
                    allocation = db.search_jcmt_allocation(
                        proposal_id=proposal.id)

        return {
            'jcmt_expertise_levels': JCMTReviewerExpertise.get_options(),
            'jcmt_ratings_justification':
                JCMTReviewRatingJustification.get_options(),
            'jcmt_ratings_technical': JCMTReviewRatingTechnical.get_options(),
            'jcmt_ratings_urgency': JCMTReviewRatingUrgency.get_options(),
            'jcmt_review': info,
            'jcmt_request': request,
            'jcmt_allocation': allocation,
        }

    def _view_proposal_decision_get(self, db, proposal, form):
        """
        Read the JCMT observing allocation from the form without raising
        parsing errors yet.
        """

        return self._read_request_form(proposal, form, skip_blank_time=True)

    def _view_proposal_decision_save(self, db, proposal, info):
        """
        Store the JCMT observing allocation.
        """

        if proposal.decision_accept and (not info.get_total().total):
            raise UserError('An accepted proposal should not have '
                            'zero total time allocation.')

        db.sync_jcmt_proposal_allocation(proposal_id=proposal.id,
                                         records=info)

    def _view_proposal_decision_extra(self, db, proposal, info):
        """
        Generate template context for the JCMT allocation on the
        decision page.
        """

        original_request = db.search_jcmt_request(proposal_id=proposal.id)
        is_prefilled = False

        if info is None:
            allocations = db.search_jcmt_allocation(proposal_id=proposal.id)

            # If there is no allocation saved, load the original request.
            if not allocations:
                # Re-write IDs as None.
                allocations = JCMTRequestCollection((
                    (n, r._replace(id=None))
                    for (n, r) in izip(count(1), original_request.values())))
                is_prefilled = True

        else:
            allocations = info

        return {
            'original_request': original_request.to_table(),
            'is_prefilled': is_prefilled,
            'allocations': allocations.values(),
            'instruments': JCMTInstrument.get_options_with_ancillary(),
            'weathers': JCMTWeather.get_available(),
        }

    @with_call_review(permission=PermissionType.EDIT)
    def view_review_call_available(self, db, call, can, form):
        type_class = self.get_call_types()
        message = None

        weathers = JCMTWeather.get_available()
        available = db.search_jcmt_available(call_id=call.id)

        if form is not None:
            updated_records = {}
            added_records = {}
            try:
                for weather_id in weathers.keys():
                    time = form.get('available_{}'.format(weather_id), '')
                    if time == '':
                        continue
                    try:
                        time = float(time)
                    except ValueError:
                        # Ignore parsing error for now so that we can return
                        # the string to the user for correction.
                        pass

                    for record in available.values():
                        if record.weather == weather_id:
                            updated_records[record.id] = record._replace(
                                time=time)
                            break
                    else:
                        added_records[weather_id] = JCMTAvailable(
                            id=None, call_id=None,
                            weather=weather_id, time=time)

                available = organise_collection(JCMTAvailableCollection,
                                                updated_records, added_records)

                updates = db.sync_jcmt_call_available(call.id, available)

                if any(updates):
                    flash('The time available has been saved.')

                raise HTTPRedirect(url_for('.review_call', call_id=call.id))

            except UserError as e:
                message = e.message

        # Straightforwardly organize available time by weather band (assuming
        # no duplicated) rather than using get_total so that we can allow for
        # unparsed strings still being present.
        available_weather = {}
        for record in available.values():
            weather = record.weather
            if not JCMTWeather.get_info(weather).available:
                weather = 0
            available_weather[weather] = record.time

        return {
            'title': 'Time Available: {} {} {}'.format(
                call.semester_name, call.queue_name,
                type_class.get_name(call.type)),
            'call': call,
            'message': message,
            'weathers': weathers,
            'available': available_weather,
        }

    def attach_review_extra(self, db, proposals):
        """
        Attach JCMT review information to each review associated with the
        given collection of proposals.
        """

        # Use list comprehension to extract proposal IDs in case proposal ID
        # isn't the collection key.
        jcmt_reviews = db.search_jcmt_review(
            proposal_id=[x.id for x in proposals.values()])

        # Update reviewer collections associated with proposals.
        for proposal in proposals.values():
            for reviewer_id in list(proposal.reviewers.keys()):
                jcmt_review = jcmt_reviews.get(reviewer_id, None)
                if jcmt_review is None:
                    jcmt_review = null_tuple(JCMTReview)

                proposal.reviewers[reviewer_id] = \
                    proposal.reviewers[reviewer_id]._replace(
                        review_extra=jcmt_review)

    def get_feedback_extra(self, db, proposal):
        """
        Get additional context to include in the proposal feedback email
        message.

        Retrieves the proposal's time allocation for display in the message.
        The allocation is returned as a sorted list of JCMTRequest objects
        with the instrument and weather entries replaced by the names of the
        corresponding instrument and weather band.
        """

        allocations = db.search_jcmt_allocation(proposal_id=proposal.id)

        return {
            'jcmt_allocation': allocations.to_sorted_list(),
        }

    @with_proposal(permission=PermissionType.EDIT)
    def view_pr_summary_edit(self, db, proposal, can, form):
        role_class = self.get_text_roles()
        return self._edit_text(
            db, proposal, role_class.PR_SUMMARY, 300,
            url_for('.pr_summary_edit', proposal_id=proposal.id), form, 10,
            target_redir=url_for('.proposal_view', proposal_id=proposal.id,
                                 _anchor='jcmt_pr_summary'))
