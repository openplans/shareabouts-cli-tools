#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, division

from shareabouts_tool import ShareaboutsTool
from argparse import ArgumentParser
import datetime
import json
import os
import pybars
import pytz
import sys
from handlebars_utils import helpers
import requests

try:
    # Python 2
    str_type = unicode
except NameError:
    # Python 3
    str_type = str


UNDEFINED = object()
dataset = None


# ============================================================================
# Handlebars helpers very specific to Shareabouts report generation

def get_place_data_for_url(url):
    place_id = int(url.rsplit('/', 1)[-1])
    place = dataset.places.get(place_id)
    place_context = place.serialize() if place else None
    return place_context

def _with_place(this, options, url):
    """
    Select the place object that corresponds to the given URL and set
    that place as the scope within the block.

    Usage: {{#with_place place}} {{properties.location_type}} {{/with_place}}
    """
    return options['fn'](get_place_data_for_url(url))
helpers['with_place'] = _with_place

def _created_between(this, options, begin, end, context=UNDEFINED):
    """
    Filter the given context (or the current scope) down to objects that have
    created_datetime values between beginning and end (left-inclusive).
    """
    if context is UNDEFINED:
        context = this

    if not context:
        return options['inverse'](this)

    def get_created_date(d):
        try:
            return d['created_datetime']
        except KeyError:
            return d['properties']['created_datetime']

    filtered_context = list(filter((lambda d: begin <= get_created_date(d) < end), context))

    if len(filtered_context) == 0:
        return options['inverse'](this)

    return options['fn'](filtered_context)
helpers['created_between'] = _created_between

def _created_within_days(this, options, daysago, context=UNDEFINED):
    """
    Filter the given context (or the current scope) down to objects that have
    created_datetime values between beginning and end (left-inclusive).
    """
    end = datetime.date.today()
    begin = end - datetime.timedelta(days=daysago)
    return _created_between(this, options, begin.isoformat(), end.isoformat()[:10], context=context)
helpers['created_within_days'] = _created_within_days

def _annotate_with_places(this, options, context=UNDEFINED):
    """
    Select the place object that corresponds to the current submission and set
    that place as the scope within the block.

    Usage: {{#with_place}} {{properties.location_type}} {{/with_place}}
    """
    if context is UNDEFINED:
        context = this

    annotated_context = []
    for submission in context:
        annotated_submission = submission.copy() if submission is not None else None
        annotated_submission['place'] = get_place_data_for_url(submission['place'])
        annotated_context.append(annotated_submission)
    return options['fn'](annotated_context)
helpers['annotate_with_places'] = _annotate_with_places



# ============================================================================


def main(config, report):
    template_filename = report.get('summary_template')
    assert template_filename, 'No template file specified'

    if 'username' in config and 'password' in config:
        auth_info = (config['username'], config['password'])
    else:
        auth_info = None

    # Download the data
    tool = ShareaboutsTool(config['host'], auth=auth_info)
    places = tool.get_places(config['owner'], config['dataset'])
    submissions = tool.get_submissions(config['owner'], config['dataset'])

    global dataset
    dataset = tool.api.account(config['owner']).dataset(config['dataset'])

    # Compile the template
    print ('Compiling and rendering the template(s): %s' % (report['summary_template'],), file=sys.stderr)

    compiler = pybars.Compiler()
    with open(report['summary_template'], 'rb') as template_file:
        template_source = template_file.read().decode()
        template = compiler.compile(template_source)

    # Convert times to local timezone
    tzname = config.get('timezone') or report.get('timezone') or None
    try:
        localtz = pytz.timezone(tzname) if tzname else pytz.utc
    except pytz.exceptions.UnknownTimeZoneError:
        print ('I do not recognize the timezone "%s".' % tzname)
        print ('To see a list of common timezone names, run '
               '"common_timezones.py".')
        return 1

    tool.convert_times(places, localtz)
    tool.convert_times(submissions, localtz)
    tool.convert_times(dataset, localtz)

    helpers['config'] = lambda this, attr: config[attr]
    helpers['report'] = lambda this, attr: report[attr]

    # Render the template
    rendered_template = template({
        'dataset': dataset.serialize(),
        'report': report,
        'config': config,
        'today': datetime.datetime.now().isoformat()
    }, helpers=helpers)

    # Print the template, and send it where it needs to go
    doc = str_type(rendered_template)
    with os.fdopen(sys.stdout.fileno(), 'wb') as stdout_b:
        stdout_b.write(doc.encode('utf-8'))

    # Send an email
    # NOTE: Remember, you must register your sender email addresses with
    #       Postmark: https://postmarkapp.com/signatures
    email_body = {
         "From" : config['email']['sender'],
         "To" : config['email']['recipient'],
         "Subject" : config['email']['subject'],
         "Bcc" : config['email']['bcc'],
         "HtmlBody" : doc,
         # "TextBody" : rendered_template,
         "ReplyTo" : config['email']['sender'],
         # "Headers" : [{}]
    }

    email_headers = {
         'Content-type': 'application/json',
         'X-Postmark-Server-Token': config['postmarkapp_token']
    }

    if doc.strip() != '':
        response = requests.post('https://api.postmarkapp.com/email',
             data=json.dumps(email_body),
            headers=email_headers
        )

        if response.status_code != 200:
            print('Received a non-success response (%s): %s' % (response.status_code, response.content), file=sys.stderr)

    return 0

if __name__ == '__main__':
    parser = ArgumentParser(description='Print the number of places in a dataset.')
    parser.add_argument('configuration', help='The dataset configuration file name')
    parser.add_argument('report', help='The report configuration file name')
    parser.add_argument('--subject', default='', help='The subject of the email to be sent.')
    parser.add_argument('--begin', help='The date from which you want results. Submissions on or after this date will be included.')
    parser.add_argument('--end', help='The date until which you want results. Submissions before this date will be included.')

    args = parser.parse_args()
    config = json.load(open(args.configuration))
    report = json.load(open(args.report))

    if args.begin: report['begin_date'] = args.begin
    if args.end: report['end_date'] = args.end

    if args.subject and 'email' in config:
        config['email']['subject'] = args.subject

    # main(config, args.template, args.begin, args.end)
    result = main(config, report) or 0
    sys.exit(result)
