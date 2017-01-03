from __future__ import absolute_import, division, print_function, \
    unicode_literals

from collections import OrderedDict
import time

from ...error import CalculatorError, UserError
from ...type.misc import SectionedList
from ...type.simple import CalculatorMode, CalculatorResult, CalculatorValue
from ...view.calculator import BaseCalculator


class RSRCalculator(BaseCalculator):
    EXPECTED = 1

    modes = OrderedDict((
        (EXPECTED, CalculatorMode('rms', 'RMS expected in given time')),
    ))

    version = 1

    @classmethod
    def get_code(cls):
        """
        Get the calculator "code".

        This is a short string used to uniquely identify the calculator
        within the facility which uses it.
        """
        return 'rsr'

    def get_default_facility_code(self):
        """
        Get the code for the facility which has the template for this
        calculator.  This method need only be overridden if the calculator
        is intended to be used by multiple facilities.
        """
        return 'rsr'

    def get_name(self):
        return 'RSR'

    def get_calc_version(self):
        return '0.1.0'

    def get_inputs(self, mode, version=None):
        if version is None:
            version = self.version
        inputs = SectionedList()
        inputs.extend([
            CalculatorValue(
                'Fl', 'Frequency between: 73 & 111 GHz', None, '{}', 'GHz.'
            ),
            CalculatorValue(
                't', 'Time of integration', None, '{}', 'min.'
            ),
        ])
        return inputs

    def get_default_input(self, mode):
        return {'Fl': 0.0, 't': 0.0}

    def parse_input(self, mode, input_, defaults=None):
        """
        Parse inputs as obtained from the HTML form (typically unicode)
        and return values suitable for calculation (perhaps float).

        If defaults are specified, these are used in place of missing
        values to avoid a UserError being raised.  This is useful
        in the case of changing mode when the form has been
        filled in incompletely.
        """

        parsed = {}

        for field in self.get_inputs(mode):
            try:
                parsed[field.code] = float(input_[field.code])

            except ValueError:
                if (not input_[field.code]) and (defaults is not None):
                    parsed[field.code] = defaults[field.code]

                else:
                    raise UserError('Invalid value for {}.', field.name)
        if float(parsed['Fl']) < 73.0 or float(parsed['Fl']) > 111.0:
            raise UserError('Invalid value for {}.', 'Frecuency')
        return parsed

    def __call__(self, mode, input_):
        """
        Method in charge to perform the calculus.
        """
        t_before = time.time()

        if mode == self.EXPECTED:
            output = {'mK': (input_['Fl'] + input_['t'])}
        else:
            raise CalculatorError('Unknown mode...')

        return CalculatorResult(output, {})

    def get_outputs(self, mode, version=None):
        """
        Get the list of calculator outputs for a given version of the
        calculator.
        """

        if version is None:
            version = self.version

        if version == 1:
            if mode == self.EXPECTED:
                return [CalculatorValue('mK', 'Result', None, '{}', 'mK')]
            else:
                raise CalculatorError('Unknown mode.')
        else:
            raise CalculatorError('Unknown version.')
