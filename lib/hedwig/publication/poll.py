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

from ..error import ConsistencyError
from ..util import get_logger
from ..type import AttachmentState, PublicationType
from .arxiv import get_pub_info_arxiv
from .ads import get_pub_info_ads, get_pub_info_doi

logger = get_logger(__name__)

PubTypeInfo = namedtuple('PubTypeInfo', ('set', 'query_function'))


def process_publication_references(db):
    """
    Function to process newly added publication references.
    """

    n_processed = 0

    types = {
        PublicationType.DOI:   PubTypeInfo(set(), get_pub_info_doi),
        PublicationType.ADS:   PubTypeInfo(set(), get_pub_info_ads),
        PublicationType.ARXIV: PubTypeInfo(set(), get_pub_info_arxiv),
    }

    logger.debug('Checking for publication references to retrieve')

    for publication in db.search_prev_proposal_pub(
            state=AttachmentState.NEW).values():

        if publication.type in types:
            types[publication.type].set.add(publication.description)

        else:
            type_name = PublicationType.get_info(publication.type).name
            logger.warning('Can not look up reference type: {}', type_name)

    for (type_, type_info) in types.items():
        if type_info.set:
            n_processed += _process_ref_type(
                db, type_, type_info.query_function, type_info.set)

    return n_processed


def _process_ref_type(db, type_, query_function, references):
    type_name = PublicationType.get_info(type_).name

    logger.debug('Retreiving {} references', type_name)

    n_processed = 0

    reference_info = query_function(list(references))

    for reference in references:
        info = reference_info.get(reference)

        if info is None:
            logger.warning(
                'No info received for {} - setting error state',
                reference)

            try:
                db.update_prev_proposal_pub(
                    type_=type_, description=reference,
                    state=AttachmentState.ERROR,
                    title=None, author=None, year=None,
                    prev_state=AttachmentState.NEW)

            except:
                logger.exception('Failed to set publication error state')

        else:
            logger.debug('Received info for {} - updating database',
                         reference)

            try:
                db.update_prev_proposal_pub(
                    type_=type_, description=reference,
                    state=AttachmentState.READY,
                    title=info.title, author=info.author, year=info.year,
                    prev_state=AttachmentState.NEW)

                n_processed += 1

            except:
                logger.exception('Failed to update publication reference')

    return n_processed