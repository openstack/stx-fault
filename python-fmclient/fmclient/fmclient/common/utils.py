# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# Copyright (c) 2018 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


from __future__ import print_function

import hashlib

import re
import six.moves.urllib.parse as urlparse
import six
import os
import copy
import argparse
import dateutil
import prettytable
import textwrap

from datetime import datetime
from dateutil import parser

from prettytable import ALL
from prettytable import FRAME
from prettytable import NONE

import wrapping_formatters


SENSITIVE_HEADERS = ('X-Auth-Token', )


class HelpFormatter(argparse.HelpFormatter):
    def start_section(self, heading):
        # Title-case the headings
        heading = '%s%s' % (heading[0].upper(), heading[1:])
        super(HelpFormatter, self).start_section(heading)


def safe_header(name, value):
    if value is not None and name in SENSITIVE_HEADERS:
        h = hashlib.sha1(value)
        d = h.hexdigest()
        return name, "{SHA1}%s" % d
    else:
        return name, value


def strip_version(endpoint):
    if not isinstance(endpoint, six.string_types):
        raise ValueError("Expected endpoint")
    version = None
    # Get rid of trailing '/' if present
    endpoint = endpoint.rstrip('/')
    url_parts = urlparse.urlparse(endpoint)
    (scheme, netloc, path, __, __, __) = url_parts
    path = path.lstrip('/')
    # regex to match 'v1' or 'v2.0' etc
    if re.match('v\d+\.?\d*', path):
        version = float(path.lstrip('v'))
        endpoint = scheme + '://' + netloc
    return endpoint, version


def endpoint_version_from_url(endpoint, default_version=None):
    if endpoint:
        endpoint, version = strip_version(endpoint)
        return endpoint, version or default_version
    else:
        return None, default_version


def env(*vars, **kwargs):
    """Search for the first defined of possibly many env vars

    Returns the first environment variable defined in vars, or
    returns the default defined in kwargs.
    """
    for v in vars:
        value = os.environ.get(v, None)
        if value:
            return value
    return kwargs.get('default', '')


def _wrapping_formatter_callback_decorator(subparser, command, callback):
    """
        - Adds the --nowrap option to a CLI command.
          This option, when on, deactivates word wrapping.
        - Decorates the command's callback function in order to process
          the nowrap flag

        :param subparser:
        :return: decorated callback
        """

    try:
        subparser.add_argument('--nowrap', action='store_true',
                               help='No wordwrapping of output')
    except Exception:
        # exception happens when nowrap option already configured
        # for command - so get out with callback undecorated
        return callback

    def no_wrap_decorator_builder(callback):

        def process_callback_with_no_wrap(cc, args={}):
            no_wrap = args.nowrap
            # turn on/off wrapping formatters when outputting CLI results
            wrapping_formatters.set_no_wrap(no_wrap)
            return callback(cc, args=args)

        return process_callback_with_no_wrap

    decorated_callback = no_wrap_decorator_builder(callback)
    return decorated_callback


def _does_command_need_no_wrap(callback):
    if callback.__name__.startswith("do_") and \
       callback.__name__.endswith("_list"):
        return True

    if callback.__name__ in \
            ['donot_config_ntp_list',
             'donot_config_ptp_list',
             'do_host_apply_memprofile',
             'do_host_apply_cpuprofile',
             'do_host_apply_ifprofile',
             'do_host_apply_profile',
             'do_host_apply_storprofile',
             'donot_config_oam_list',
             'donot_dns_list',
             'do_host_cpu_modify',
             'do_event_suppress',
             'do_event_unsuppress',
             'do_event_unsuppress_all']:
        return True
    return False


def get_terminal_size():
    """Returns a tuple (x, y) representing the width(x) and the height(x)
    in characters of the terminal window.
    """

    def ioctl_GWINSZ(fd):
        try:
            import fcntl
            import struct
            import termios
            cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ,
                                                 '1234'))
        except Exception:
            return None
        if cr == (0, 0):
            return None
        if cr == (0, 0):
            return None
        return cr

    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except Exception:
            pass
    if not cr:
        cr = (os.environ.get('LINES', 25), os.environ.get('COLUMNS', 80))
    return int(cr[1]), int(cr[0])


def normalize_field_data(obj, fields):
    for f in fields:
        if hasattr(obj, f):
            data = getattr(obj, f, '')
            try:
                data = str(data)
            except UnicodeEncodeError:
                setattr(obj, f, data.encode('utf-8'))


# Decorator for cli-args
def arg(*args, **kwargs):
    def _decorator(func):
        # Because of the sematics of decorator composition if we just append
        # to the options list positional options will appear to be backwards.
        func.__dict__.setdefault('arguments', []).insert(0, (args, kwargs))
        return func

    return _decorator


def define_command(subparsers, command, callback, cmd_mapper):
    '''Define a command in the subparsers collection.

    :param subparsers: subparsers collection where the command will go
    :param command: command name
    :param callback: function that will be used to process the command
    '''
    desc = callback.__doc__ or ''
    help = desc.strip().split('\n')[0]
    arguments = getattr(callback, 'arguments', [])

    subparser = subparsers.add_parser(command, help=help,
                                      description=desc,
                                      add_help=False,
                                      formatter_class=HelpFormatter)
    subparser.add_argument('-h', '--help', action='help',
                           help=argparse.SUPPRESS)

    # Are we a list command?
    if _does_command_need_no_wrap(callback):
        # then decorate it with wrapping data formatter functionality
        func = _wrapping_formatter_callback_decorator(subparser, command, callback)
    else:
        func = callback

    cmd_mapper[command] = subparser
    for (args, kwargs) in arguments:
        subparser.add_argument(*args, **kwargs)
    subparser.set_defaults(func=func)


def define_commands_from_module(subparsers, command_module, cmd_mapper):
    '''Find all methods beginning with 'do_' in a module, and add them
    as commands into a subparsers collection.
    '''
    for method_name in (a for a in dir(command_module) if a.startswith('do_')):
        # Commands should be hypen-separated instead of underscores.
        command = method_name[3:].replace('_', '-')
        callback = getattr(command_module, method_name)
        define_command(subparsers, command, callback, cmd_mapper)


def parse_date(string_data):
    """Parses a date-like input string into a timezone aware Python
    datetime.
    """

    if not isinstance(string_data, six.string_types):
        return string_data

    pattern = r'(\d{4}-\d{2}-\d{2}[T ])?\d{2}:\d{2}:\d{2}(\.\d{6})?Z?'

    def convert_date(matchobj):
        formats = ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f",
                   "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                   "%Y-%m-%dT%H:%M:%SZ"]
        datestring = matchobj.group(0)
        if datestring:
            for format in formats:
                try:
                    datetime.strptime(datestring, format)
                    datestring += "+0000"
                    parsed = parser.parse(datestring)
                    converted = parsed.astimezone(dateutil.tz.tzlocal())
                    converted = datetime.strftime(converted, format)
                    return converted
                except Exception:
                    pass
        return datestring

    return re.sub(pattern, convert_date, string_data)


def _sort_for_list(objs, fields, formatters={}, sortby=0, reversesort=False):

    # Sort only if necessary
    if sortby is None:
        return objs

    sort_field = fields[sortby]
    # figure out sort key function
    if sort_field in formatters:
        field_formatter = formatters[sort_field]
        if wrapping_formatters.WrapperFormatter.is_wrapper_formatter(
                field_formatter):
            def sort_key(x):
                return field_formatter.wrapper_formatter.get_unwrapped_field_value(x)
        else:
            def sort_key(x):
                return field_formatter(x)
    else:
        def sort_key(x):
            return getattr(x, sort_field, '')

    objs.sort(reverse=reversesort, key=sort_key)

    return objs


def str_height(text):
    if not text:
        return 1
    lines = str(text).split("\n")
    height = len(lines)
    return height


def row_height(texts):
    if not texts or len(texts) == 0:
        return 1
    height = max(str_height(text) for text in texts)
    return height


class WRPrettyTable(prettytable.PrettyTable):
    """A PrettyTable that allows word wrapping of its headers."""

    def __init__(self, field_names=None, **kwargs):
        super(WRPrettyTable, self).__init__(field_names, **kwargs)

    def _stringify_header(self, options):
        """
          This overridden version of _stringify_header can wrap its
          header data.  It leverages the functionality in  _stringify_row
          to perform this task.
          :returns string of header, including border text
        """
        bits = []
        if options["border"]:
            if options["hrules"] in (ALL, FRAME):
                bits.append(self._hrule)
                bits.append("\n")
        # For tables with no data or field names
        if not self._field_names:
            if options["vrules"] in (ALL, FRAME):
                bits.append(options["vertical_char"])
                bits.append(options["vertical_char"])
            else:
                bits.append(" ")
                bits.append(" ")

        header_row_data = []
        for field in self._field_names:
            if options["fields"] and field not in options["fields"]:
                continue
            if self._header_style == "cap":
                fieldname = field.capitalize()
            elif self._header_style == "title":
                fieldname = field.title()
            elif self._header_style == "upper":
                fieldname = field.upper()
            elif self._header_style == "lower":
                fieldname = field.lower()
            else:
                fieldname = field
            header_row_data.append(fieldname)

        # output actual header row data, word wrap when necessary
        bits.append(self._stringify_row(header_row_data, options))

        if options["border"] and options["hrules"] != NONE:
            bits.append("\n")
            bits.append(self._hrule)

        return "".join(bits)


def prettytable_builder(field_names=None, **kwargs):
    return WRPrettyTable(field_names, **kwargs)


def wordwrap_header(field, field_label, formatter):
    """
      Given a field label (the header text for one column) and the word wrapping formatter for a column,
      this function asks the formatter for the desired column width and then
      performs a wordwrap of field_label

    :param field:  the field name associated with the field_label
    :param field_label:  field_label to word wrap
    :param formatter: the field formatter
    :return: word wrapped field_label
    """
    if wrapping_formatters.is_nowrap_set():
        return field_label

    if not wrapping_formatters.WrapperFormatter.is_wrapper_formatter(formatter):
        return field_label
    # go to the column's formatter and ask it what the width should be
    wrapper_formatter = formatter.wrapper_formatter
    actual_width = wrapper_formatter.get_actual_column_char_len(wrapper_formatter.get_calculated_desired_width())
    # now word wrap based on column width
    wrapped_header = textwrap.fill(field_label, actual_width)
    return wrapped_header


def default_printer(s):
    print(s)


def pt_builder(field_labels, fields, formatters, paging, printer=default_printer):
    """
      returns an object that 'fronts' a prettyTable object
      that can handle paging as well as automatically falling back
      to not word wrapping when word wrapping does not cause the
      output to fit the terminal width.
    """

    class PT_Builder(object):

        def __init__(self, field_labels, fields, formatters, no_paging):
            self.objs_in_pt = []
            self.unwrapped_field_labels = field_labels
            self.fields = fields
            self.formatters = formatters
            self.header_height = 0
            self.terminal_width, self.terminal_height = get_terminal_size()
            self.terminal_lines_left = self.terminal_height
            self.paging = not no_paging
            self.paged_rows_added = 0
            self.pt = None
            self.quit = False

        def add_row(self, obj):
            if self.quit:
                return False
            if not self.pt:
                self.build_pretty_table()
            return self._row_add(obj)

        def __add_row_and_obj(self, row, obj):
            self.pt.add_row(row)
            self.objs_in_pt.append(obj)

        def _row_add(self, obj):

            row = _build_row_from_object(self.fields, self.formatters, obj)

            if not paging:
                self.__add_row_and_obj(row, obj)
                return True

            rheight = row_height(row)
            if (self.terminal_lines_left - rheight) >= 0 or self.paged_rows_added == 0:
                self.__add_row_and_obj(row, obj)
                self.terminal_lines_left -= rheight
            else:
                printer(self.get_string())
                if self.terminal_lines_left > 0:
                    printer("\n" * (self.terminal_lines_left - 1))

                s = six.moves.input("Press Enter to continue or 'q' to exit...")
                if s == 'q':
                    self.quit = True
                    return False
                self.terminal_lines_left = self.terminal_height - self.header_height
                self.build_pretty_table()
                self.__add_row_and_obj(row, obj)
                self.terminal_lines_left -= rheight
            self.paged_rows_added += 1

        def get_string(self):
            if not self.pt:
                self.build_pretty_table()
            objs = copy.copy(self.objs_in_pt)
            self.objs_in_pt = []
            output = self.pt.get_string()
            if wrapping_formatters.is_nowrap_set():
                return output
            output_width = wrapping_formatters.get_width(output)
            if output_width <= self.terminal_width:
                return output
            # At this point pretty Table (self.pt) does not fit the terminal width so let's
            # temporarily turn wrapping off, rebuild the pretty Table with the data unwrapped.
            orig_no_wrap_settings = wrapping_formatters.set_no_wrap_on_formatters(True, self.formatters)
            self.build_pretty_table()
            for o in objs:
                self.add_row(o)
            wrapping_formatters.unset_no_wrap_on_formatters(orig_no_wrap_settings)
            return self.pt.get_string()

        def build_pretty_table(self):
            field_labels = [wordwrap_header(field, field_label, formatter)
                            for field, field_label, formatter in
                            zip(self.fields, self.unwrapped_field_labels, [formatters.get(f, None)
                                                                           for f in self.fields])]
            self.pt = prettytable_builder(field_labels, caching=False, print_empty=False)
            self.pt.align = 'l'
            # 2 header border lines + 1 bottom border + 1 prompt + header data height
            self.header_height = 2 + 1 + 1 + row_height(field_labels)
            self.terminal_lines_left = self.terminal_height - self.header_height
            return self.pt

        def done(self):
            if self.quit:
                return

            if not self.paging or (self.terminal_lines_left < self.terminal_height - self.header_height):
                printer(self.get_string())

    return PT_Builder(field_labels, fields, formatters, not paging)


def print_long_list(objs, fields, field_labels, formatters={}, sortby=0, reversesort=False, no_wrap_fields=[],
                    no_paging=False, printer=default_printer):

    formatters = wrapping_formatters.as_wrapping_formatters(objs, fields, field_labels, formatters,
                                                            no_wrap_fields=no_wrap_fields)

    objs = _sort_for_list(objs, fields, formatters=formatters, sortby=sortby, reversesort=reversesort)

    pt = pt_builder(field_labels, fields, formatters, not no_paging, printer=printer)

    for o in objs:
        pt.add_row(o)

    pt.done()


def print_dict(d, dict_property="Property", wrap=0):
    pt = prettytable.PrettyTable([dict_property, 'Value'],
                                 caching=False, print_empty=False)
    pt.align = 'l'
    for k, v in sorted(d.iteritems()):
        v = parse_date(v)
        # convert dict to str to check length
        if isinstance(v, dict):
            v = str(v)
        if wrap > 0:
            v = textwrap.fill(six.text_type(v), wrap)
        # if value has a newline, add in multiple rows
        # e.g. fault with stacktrace
        if v and isinstance(v, str) and r'\n' in v:
            lines = v.strip().split(r'\n')
            col1 = k
            for line in lines:
                pt.add_row([col1, line])
                col1 = ''
        else:
            pt.add_row([k, v])

    print(pt.get_string())


def _build_row_from_object(fields, formatters, o):
    """
      takes an object o and converts to an array of values
      compatible with the input for prettyTable.add_row(row)
    """
    row = []
    for field in fields:
        if field in formatters:
            data = parse_date(getattr(o, field, ''))
            setattr(o, field, data)
            data = formatters[field](o)
            row.append(data)
        else:
            data = parse_date(getattr(o, field, ''))
            row.append(data)
    return row


def print_list(objs, fields, field_labels, formatters={}, sortby=0,
               reversesort=False, no_wrap_fields=[], printer=default_printer):
    # print_list() is the same as print_long_list() with paging turned off
    return print_long_list(objs, fields, field_labels, formatters=formatters, sortby=sortby,
                           reversesort=reversesort, no_wrap_fields=no_wrap_fields,
                           no_paging=True, printer=printer)
