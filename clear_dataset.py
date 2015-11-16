#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, division
from shareabouts_tool import ShareaboutsTool
from argparse import ArgumentParser
import json

spinner_frames = '\|/―'
step = 0

def place_done_callback(place, place_response):
    import sys
    global step

    if place_response.status_code != 204:
        print('Error deleting place %s: %s (%s)' % (place, place_response.status_code, place_response.text))
        return
    else:
        print('\r%s - Deleted %s  ' % (step, spinner_frames[step % 4]), end='')
    sys.stdout.flush()

    step += 1

def place_matches_filters(place, included_attributes=[], restricted_attributes=[], eq_attribute_values={}, ne_attribute_values={}):
    for attr in included_attributes:
        if attr not in place:
            return False
    for attr in restricted_attributes:
        if attr in place:
            return False
    for attr, val in eq_attribute_values.items():
        if place.get(attr, None) != val:
            return False
    for attr, val in ne_attribute_values.items():
        if place.get(attr, None) == val:
            return False
    return True

def main(config, delete=True, included_attributes=[], restricted_attributes=[], eq_attribute_values={}, ne_attribute_values={}):
    tool = ShareaboutsTool(config['host'])
    all_places = [
        place for place in
        tool.get_places(config['owner'], config['dataset'])
        #...put a condition here to filter the places, if desired...
        if place_matches_filters(
            place, included_attributes, restricted_attributes,
            eq_attribute_values, ne_attribute_values)
    ]

    print('Deleting the %s places...' % (len(all_places),))

    if delete:
        tool.delete_places(
            config['owner'], config['dataset'], config['key'],
            all_places, place_done_callback)

    print('\nDone!')

if __name__ == '__main__':
    parser = ArgumentParser(description='Remove all places from a dataset.')
    parser.add_argument('configuration', type=str, help='The configuration file name')
    parser.add_argument('--test', '--no-delete', dest='delete', action='store_false', help='Actually delete the places?')
    parser.add_argument('--has-attr', nargs='*', help='Delete items that have the attribute(s)')
    parser.add_argument('--wo-attr', nargs='*', help='Delete items that do not have the attribute(s)')
    parser.add_argument('--attr-is', nargs='*', help='Delete items that have the specific attribute values')
    parser.add_argument('--attr-not', nargs='*', help='Delete items that do not have the specific attribute values')

    args = parser.parse_args()
    config = json.load(open(args.configuration))

    main(
        config, delete=args.delete,
        included_attributes=args.has_attr, restricted_attributes=args.wo_attr,
        eq_attribute_values=dict([item.split('=') for item in args.attr_is]),
        ne_attribute_values=dict([item.split('=') for item in args.attr_not]),
    )
