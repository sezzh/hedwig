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

from collections import namedtuple, OrderedDict
import time

from jcmt_itc_scuba2 import SCUBA2ITC

from ...error import CalculatorError, UserError
from ...type import CalculatorMode, CalculatorResult, CalculatorValue
from ...view.calculator import BaseCalculator
from ...view.util import parse_time

WeatherBand = namedtuple('WeatherBand', ('rep', 'min', 'max'))


class SCUBA2Calculator(BaseCalculator):
    CALC_TIME = 1
    CALC_RMS = 2

    modes = OrderedDict((
        (CALC_TIME, CalculatorMode('time', 'Time required for target RMS')),
        (CALC_RMS,  CalculatorMode('rms',  'RMS expected in given time')),
    ))

    bands = OrderedDict((
        (1, WeatherBand(0.045, None, 0.05)),
        (2, WeatherBand(0.065, 0.05, 0.08)),
        (3, WeatherBand(0.1,   0.08, 0.12)),
        (4, WeatherBand(0.16,  0.12, 0.2)),
        (5, WeatherBand(0.23,  0.2,  None)),
    ))

    default_pix850 = 8.0
    default_pix450 = 4.0

    version = 1

    @classmethod
    def get_code(cls):
        """
        The the calculator "code".

        This is a short string used to uniquely identify the calculator
        within the facility which uses it.
        """

        return 'scuba2'

    def __init__(self, *args):
        """
        Construct calculator.

        Calls the superclass constructor and then initializes a SCUBA-2
        ITC object.
        """

        super(SCUBA2Calculator, self).__init__(*args)

        self.itc = SCUBA2ITC()

    def get_name(self):
        return 'SCUBA-2 ITC'

    def get_inputs(self, mode, version=None):
        """
        Get the list of calculator inputs for a given version of the
        calculator.
        """

        if version is None:
            version = self.version

        if version == 1:
            common_inputs = [
                CalculatorValue(
                    'map',    'Map type',           'Map', '{}', None),
                CalculatorValue(
                    'dec',    'Source declination', 'Dec', '{:.3g}', 'degrees'),
                CalculatorValue(
                    'mf',     'Matched filter',
                    'Match. filt.', '{}', None),
                CalculatorValue(
                    'pix850', '850 \u00b5m pixel size',  '850 \u00b5m pix', '{}', '"'),
                CalculatorValue(
                    'pix450', '450 \u00b5m pixel size',  '450 \u00b5m pix', '{}', '"'),
                CalculatorValue(
                    'tau',    '225 GHz opacity',
                    '\u03c4\u2082\u2082\u2085', '{}', None),
            ]
        else:
            raise CalculatorError('Unknown version.')

        if mode == self.CALC_TIME:
            if version == 1:
                return common_inputs + [
                    CalculatorValue(
                        'wl',  'Wavelength', '\u03bb', '{}', '\u00b5m'),
                    CalculatorValue(
                        'rms', 'Target sensitivity', '\u03c3',
                        '{:.3f}', 'mJy/beam'),
                ]
            else:
                raise CalculatorError('Unknown version.')

        elif mode == self.CALC_RMS:
            if version == 1:
                return common_inputs + [
                    CalculatorValue(
                        'time', 'Observing time', 'Time', '{:.3f}', 'hours'),
                ]
            else:
                raise CalculatorError('Unknown version.')

        else:
            raise CalculatorError('Unknown mode.')

    def get_default_input(self, mode):
        """
        Get the default input values (for the current version).
        """

        common_inputs = [
            ('map', 'daisy'),
            ('dec', 40.0),
            ('tau', 0.065),
            ('pix850', self.default_pix850),
            ('pix450', self.default_pix450),
            ('mf', False),
        ]

        if mode == self.CALC_TIME:
            return dict(common_inputs + [
                ('wl', 850),
                ('rms', 2.0),
            ])

        elif mode == self.CALC_RMS:
            return dict(common_inputs + [
                ('time', 30),
            ])

        else:
            raise CalculatorError('Unknown mode.')

    def format_input(self, inputs, values):
        """
        Format input values for display in the input form.
        """

        formatted_inputs = {
            x.code:
                x.format.format(values[x.code])
                if x.code not in ('map', 'mf', 'wl')
                else values[x.code]
            for x in inputs
        }

        for (band_num, band_info) in self.bands.items():
            if abs(values['tau'] - band_info.rep) < 0.0001:
                formatted_inputs['tau_band'] = band_num
                break
        else:
            formatted_inputs['tau_band'] = None

        return formatted_inputs

    def get_form_input(self, inputs, form):
        """
        Extract the input values from the submitted form.
        """

        values = {}

        for input_ in inputs:
            if input_.code == 'mf':
                values[input_.code] = input_.code in form

            elif input_.code == 'pix850' or input_.code == 'pix450':
                # These aren't present in the form if matched filter is
                # selected.
                if 'mf' in form:
                    values[input_.code] = (
                        self.default_pix850 if input_.code == 'pix850' else
                        self.default_pix450)
                else:
                    values[input_.code] = form[input_.code]

            elif input_.code == 'tau':
                if form['tau_band'] == 'other':
                    values['tau_band'] = None
                    values['tau'] = form['tau_value']
                else:
                    tau_band = values['tau_band'] = int(form['tau_band'])
                    values['tau'] = self.bands[tau_band].rep

            elif input_.code == 'wl':
                values[input_.code] = int(form[input_.code])

            else:
                values[input_.code] = form[input_.code]

        return values

    def convert_input_mode(self, mode, new_mode, input_):
        """
        Convert the inputs for one mode to form a suitable set of inputs
        for another mode.  Only called if the mode is changed.
        """

        new_input = input_.copy()

        output = self(mode, input_).output

        if mode == self.CALC_RMS and new_mode == self.CALC_TIME:
            del new_input['time']
            new_input['wl'] = 850
            new_input['rms'] = output['rms_850']

        elif mode == self.CALC_TIME and new_mode == self.CALC_RMS:
            del new_input['rms']
            del new_input['wl']
            new_input['time'] = output['time']

        else:
            raise CalculatorError('Impossible mode change.')

        return new_input

    def convert_input_version(self, old_version, input_):
        """
        Converts the inputs from an older version so that they can be
        used with the current version of the calculator.
        """

        return input_

    def get_outputs(self, mode, version=None):
        """
        Get the list of calculator outputs for a given version of the
        calculator.
        """

        if version is None:
            version = self.version

        if mode == self.CALC_TIME:
            if version == 1:
                return [
                    CalculatorValue(
                        'time', 'Observing time', 'Time', '{:.3f}', 'hours'),
                ]
            else:
                raise CalculatorError('Unknown version.')

        elif mode == self.CALC_RMS:
            if version == 1:
                return [
                    CalculatorValue(
                        'rms_850', '850 \u00b5m sensitivity',
                        '\u03c3\u2088\u2085\u2080', '{:.3f}', 'mJy/beam'),
                    CalculatorValue(
                        'rms_450', '450 \u00b5m sensitivity',
                        '\u03c3\u2084\u2085\u2080', '{:.3f}', 'mJy/beam'),
                ]
            else:
                raise CalculatorError('Unknown version.')

        else:
            raise CalculatorError('Unknown mode.')

    def get_extra_context(self):
        """
        Return extra information to be given to the view template.
        """

        return {
            'weather_bands': self.bands,
            'map_modes': self.itc.get_modes(),
            'default': {
                'pix850': self.default_pix850,
                'pix450': self.default_pix450,
            },
        }

    def parse_input(self, mode, input_):
        """
        Parse inputs as obtained from the HTML form (typically unicode)
        and return values suitable for calculation (perhaps float).
        """

        parsed = {}

        for field in self.get_inputs(mode):
            try:
                if field.code in ('dec', 'pix850', 'pix450', 'rms', 'tau'):
                    parsed[field.code] = float(input_[field.code])

                elif field.code == 'time':
                    parsed[field.code] = parse_time(input_[field.code])

                else:
                    parsed[field.code] = input_[field.code]

            except ValueError:
                raise UserError('Invalid value for {}.', field.name)

        if not -90 <= parsed['dec'] <= 90:
            raise UserError('Source declination should be between -90 and 90.')

        return parsed

    def __call__(self, mode, input_):
        """
        Perform a calculation, taking an input dictionary and returning
        a CalculatorResult object.

        The result object contains the essential output, a dictionary with
        entries corresponding to the list given by get_outputs.  It also
        contains any extra output for display but which would not be
        stored in the database as part of the calculation result.
        """

        map_mode = input_['map']
        extra = {}

        # Determine sampling factors.
        if input_['mf']:
            factor = {850: 5, 450: 8}
        else:
            factor = {850: (input_['pix850'] / 4) ** 2,
                      450: (input_['pix450'] / 2) ** 2}

        extra['f_850'] = factor[850]
        extra['f_450'] = factor[450]

        extra['airmass'] = airmass = self.itc.estimate_airmass(input_['dec'])

        # Determine tau and transmission at each wavelength.
        tau = {}
        transmission = {}
        for filter_ in (850, 450):
            tau_wl = self.itc.calculate_tau(filter_, input_['tau'])
            tau[filter_] = tau_wl
            extra['tau_{}'.format(filter_)] = tau_wl

            transmission_wl = self.itc.calculate_transmission(airmass, tau_wl)
            transmission[filter_] = transmission_wl
            extra['trans_{}'.format(filter_)] = transmission_wl

        # Perform calculation.
        if mode == self.CALC_TIME:
            filter_ = input_['wl']
            filter_alt = 850 if filter_ == 450 else 450

            time_src = self.itc.calculate_time(
                map_mode, filter_, transmission[filter_], factor[filter_],
                input_['rms'])

            extra['time_src'] = time_src / 3600.0

            extra['wl_alt'] = filter_alt
            extra['rms_alt'] = self.itc.calculate_rms(
                map_mode, filter_alt, transmission[filter_alt],
                factor[filter_alt], time_src)

            time_tot = time_src + self.itc.estimate_overhead(map_mode,
                                                             time_src)

            output = {'time': time_tot / 3600.0}

        elif mode == self.CALC_RMS:
            # Convert time to seconds.
            time_tot = input_['time'] * 3600.0

            time_src = time_tot - self.itc.estimate_overhead(map_mode,
                                                             time_tot,
                                                             from_total=True)
            extra['time_src'] = time_src / 3600.0

            output = {
                'rms_850': self.itc.calculate_rms(
                    map_mode, 850, transmission[850], factor[850], time_src),
                'rms_450': self.itc.calculate_rms(
                    map_mode, 450, transmission[450], factor[450], time_src),
            }

        else:
            raise CalculatorError('Unknown mode.')

        return CalculatorResult(output, extra)