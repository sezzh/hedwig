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

from ...error import NoSuchRecord, UserError
from ...type import Affiliation, Call, Queue, ResultCollection, Semester
from ...util import get_countries
from ...view import auth
from ...web.util import ErrorPage, HTTPError, HTTPForbidden, \
    HTTPNotFound, HTTPRedirect, \
    flash, session, url_for
from ...view.util import organise_collection


class GenericProposal(object):
    def view_proposal_new(self, db, call_id, form, is_post):
        try:
            call = db.search_call(
                facility_id=self.id_, call_id=call_id
            ).get_single()
        except NoSuchRecord:
            raise HTTPNotFound('Call not found')
        except MultipleRecords:
            raise HTTPError('Multiple calls found')
        # TODO: check call is open.
        # if not call.open:
        #    raise ErrorPage('This call is not currently open for proposals.')

        affiliations = db.search_affiliation(
            facility_id=self.id_, hidden=False)
        if not affiliations:
            raise HTTPError('No affiliations appear to be available.')

        message = None

        proposal_title = ''
        affiliation_id = None

        if is_post:
            proposal_title = form['proposal_title']

            affiliation_id = int(form['affiliation_id'])
            if affiliation_id not in affiliations:
                raise ErrorPage('Invalid affiliation selected.')

            try:
                proposal_id = db.add_proposal(
                    call_id=call_id, person_id=session['person']['id'],
                    affiliation_id=affiliation_id,
                    title=proposal_title)
                flash('Your new proposal has been created.')
                raise HTTPRedirect(url_for('.proposal_view',
                                           proposal_id=proposal_id))

            except UserError as e:
                message = e.message

        return {
            'title': 'New Proposal',
            'call': call,
            'message': message,
            'proposal_title': proposal_title,
            'affiliations': affiliations.values(),
            'affiliation_id': affiliation_id
        }

    def view_proposal_view(self, db, proposal_id):
        try:
            proposal = db.get_proposal(self.id_, proposal_id,
                                       with_members=True)
        except NoSuchRecord:
            raise HTTPNotFound('Proposal not found')

        can = auth.for_proposal(db, proposal)

        if not can.view:
            raise HTTPForbidden('Permission denied for this proposal.')

        countries = get_countries()

        return {
            'title': proposal.title,
            'can_edit': can.edit,
            'proposal': proposal._replace(members=[
                x._replace(institution_country=countries.get(
                    x.institution_country, 'Unknown country'))
                for x in proposal.members.values()]),
        }
