#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Generate a clean CSV dump of Shareabouts API data. Uses a mapping from the
template config file to transform data from the API into clean CSVs.

For example, your templates/ds.json file may look something like:

{
    "summary_template": "templates/ds.html",

    "postmarkapp_token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "email": {
        "sender": "admin@example.com",
        "recipient": "client@example.com"
    },

    "comments_csv": {
        "field_map": {
            "created_datetime": "submitted_at",
            "place": "idea_id",
            "submitter.name": "submitter_name"
        },
        "field_order": [
            "submitted_at",
            "idea_id",
            "comment",
            "submitter_name",
            "id",
            "user_token",
            "visible"
        ]
    },

    "places_csv": {
        "field_map": {
            "attachments.0.file": "image_url",
            "created_datetime": "submitted_at",
            "geometry": "location_x_y",
            "submission_sets.comments.length": "comments_count",
            "submission_sets.support.length": "support_count",
            "submitter.name": "submitter_name",
            "submitter.provider_type": "submitter.network_type",
            "submitter.provider_id": "submitter.network_id"
        },
        "field_order": [
            "submitted_at",
            "title",
            "description",
            "details",
            "location_x_y",
            "image_url",
            "comments_count",
            "support_count",
            "submitter_name",
            "submitter.avatar_url",
            "submitter.network_type",
            "submitter.network_id",
            "submitter.username",
            "private-email",
            "private-phone",
            "id",
            "user_token",
            "visible"
        ]
    }
}
"""

from __future__ import print_function, unicode_literals, division

from shareabouts_tool import ShareaboutsTool
from argparse import ArgumentParser
import csv
import json
import pytz
import sys

try:
    from cStringIO import StringIO
except:
    from StringIO import StringIO

try:
    # Python 2
    str_type = unicode
except NameError:
    # Python 3
    str_type = str


UNDEFINED = object()
dataset = None




def main(config, report, set_name, force_new=False):
    csv_config = report.get('%s_csv' % (set_name,), {})

    # csv_infilename = csv_config.get('infile')
    # assert csv_infilename, 'No input file specified'

    if 'username' in config and 'password' in config:
        auth_info = (config['username'], config['password'])
    else:
        auth_info = None

    # Download the data
    tool = ShareaboutsTool(config['host'], auth=auth_info)
    csv_string = tool.get_snapshot(config['owner'], config['dataset'], set_name=set_name, format='csv', force_new=force_new)

    # Convert times to local timezone
    tzname = config.get('timezone') or report.get('timezone') or None
    try:
        localtz = pytz.timezone(tzname) if tzname else pytz.utc
    except pytz.exceptions.UnknownTimeZoneError:
        print ('I do not recognize the timezone "%s".' % tzname)
        print ('To see a list of common timezone names, run '
               '"common_timezones.py".')
        return 1

    begin_dt = report.get('begin_date')
    end_dt = report.get('end_date')

    # Transform the CSV data
    print ('Transforming the data...', file=sys.stderr)
    infile = StringIO(csv_string)
    reader = csv.DictReader(infile)

    data = []
    for row in reader:
        tool.convert_times(row, localtz)

        if begin_dt and row['created_datetime'] < begin_dt:
            continue
        if end_dt and row['created_datetime'] >= end_dt:
            continue

        for infield, outfield in csv_config.get('field_map', {}).items():
            if infield in row and row[infield]:
                row[outfield] = row.pop(infield)

        data.append(row)

    # Print the template, and send it where it needs to go
    outfile = sys.stdout
    writer = csv.DictWriter(outfile,
        fieldnames=csv_config.get('field_order', reader.fieldnames),
        extrasaction='ignore')
    writer.writeheader()
    writer.writerows(data)

    return 0

if __name__ == '__main__':
    parser = ArgumentParser(description='Dump data from the Shareabouts API into a clean CSV.')
    parser.add_argument('configuration', help='The dataset access configuration file name')
    parser.add_argument('report', help='The report/data output configuration file name')
    parser.add_argument('--set_name', help='The name of the set to snapshot', default='places')
    parser.add_argument('--force_new', help='Force the API server to create a new snapshot', default=False, action='store_true')
    parser.add_argument('--begin', default='0001-01-01', help='The date/time from which you want results. Submissions on or after this date/time will be included.')
    parser.add_argument('--end', default='9999-12-31T23:59:59.999', help='The date/time until which you want results. Submissions before this date/time will be included.')

    args = parser.parse_args()
    config = json.load(open(args.configuration))
    report = json.load(open(args.report))

    if args.begin: report['begin_date'] = args.begin
    if args.end: report['end_date'] = args.end

    # main(config, args.template, args.begin, args.end)
    result = main(config, report, args.set_name, force_new=args.force_new) or 0
    sys.exit(result)
