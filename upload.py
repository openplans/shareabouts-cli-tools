#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, division
from shareabouts_tool import ShareaboutsTool
from argparse import ArgumentParser
import json
import sys

spinner_frames = '\|/―'
step = 0

def place_done_callback(place, place_response):
    global step

    step += 1

    if place_response.status_code == 200:
        print('\r%s - Saved   %s  ' % (step, spinner_frames[step % 4]), end='')
    elif place_response.status_code == 201:
        print('\r%s - Created %s  ' % (step, spinner_frames[step % 4]), end='')
    elif place_response.status_code == 204:
        print('\r%s - Deleted %s  ' % (step, spinner_frames[step % 4]), end='')
    else:
        print('Error saving place %s: %s (%s)' % (place, place_response.status_code, place_response.text))
        return
    sys.stdout.flush()

def get_gone_places(config, mapped_places, loaded_places):
    source_id_field = config.get('source_id_field', None)
    loaded_ids = set([
        place['properties'].get(source_id_field or 'id')
        for place in loaded_places])
    gone_places = [place for (mapped_id, place) in mapped_places.items() if mapped_id not in loaded_ids]
    return gone_places

def main(config, silent=True, create=True, update=True, delete=False, partial=True):
    if 'username' in config and 'password' in config:
        auth_info = (config['username'], config['password'])
    else:
        auth_info = None

    tool = ShareaboutsTool(config['host'], auth=auth_info)
    all_places = tool.get_places(config['owner'], config['dataset'])
    mapped_places = tool.get_source_place_map(all_places, mapped_id_field=config.get('mapped_id_field', '_imported_id'))

    if config['source_file'].endswith('geojson'):
        load_func = tool.updated_from_geojson
    elif config['source_file'].endswith('csv'):
        load_func = tool.updated_from_csv
    else:
        raise ValueError('Unrecognized extension for source file: %s' % (config['source_file'],))

    loaded_places = load_func(
        mapped_places, config['source_file'],
        include_fields=set(config.get('fields', [])),
        mapped_fields=config.get('mapped_fields', {}),
        source_id_field=config.get('source_id_field', None),
        mapped_id_field=config.get('mapped_id_field', '_imported_id'),
        default_values=config.get('default_values', {}))

    if create or update:
        print('Saving the places...')

        tool.save_places(
            config['owner'], config['dataset'], config['key'],
            loaded_places, place_done_callback, silent=silent, create=create, update=update, partial=partial)

    gone_places = get_gone_places(config, mapped_places, loaded_places)
    gone_place_urls = [str(place.get('url')) for place in gone_places]
    print('\n%s places are no longer present in the imported data:\n  - %s' % (len(gone_places), '\n  - '.join(gone_place_urls)))

    if delete:
        print('Deleting the places...')
        global step
        step = 1
        tool.delete_places(
            config['owner'], config['dataset'], config['key'],
            gone_places, place_done_callback)

    if not (create or update or delete):
        print ('\nTo modify the data in the dataset, use the create (-c), update (-u), or delete (-d) flags. Run --help for more information.')

    print('\nDone!')

if __name__ == '__main__':
    parser = ArgumentParser(description='Modify the data in a dataset based on an input file specified in the configuration file.')
    parser.add_argument('configuration', type=str, help='The configuration file name')
    parser.add_argument('-c', '--create', dest='create', action='store_true', help='Create non-existant places')
    parser.add_argument('-u', '--update', dest='update', action='store_true', help='Update pre-existing places')
    parser.add_argument('-r', '--replace', dest='replace', action='store_true', help='Replace existing updated places in full, instead of doing a partial update')
    parser.add_argument('-d', '--delete', dest='delete', action='store_true', help='Delete no longer existing places')
    parser.add_argument('-A', '--do-all', dest='allmod', action='store_true', help='Do all modifiation actions; equivalent to -cud')
    parser.add_argument('-V', '--activity', dest='silent', action='store_false' ,help='Create dataset activity when creating and updating places')

    args = parser.parse_args()
    config = json.load(open(args.configuration))

    if args.allmod:
        args.create = True
        args.update = True
        args.delete = True

    main(config, create=args.create, update=args.update, delete=args.delete, silent=args.silent, partial=not args.replace)
