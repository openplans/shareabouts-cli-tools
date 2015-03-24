from __future__ import print_function, unicode_literals, division

import csv
import json
import math
import pytz
import requests
import sys
import threading
import time
from shareabouts import ShareaboutsApi

try:
    cli_input = raw_input
except NameError:
    cli_input = input

try:
    str_base = basestring
except NameError:
    str_base = str


def chunks_of(iterable, max_len):
    """
    Split the iterable into chunks (tuples) of no more than max_len length.
    """
    source = iter(iterable)

    no_more = False
    while True:
        # Build up a chunk that is at most max_len elements. If we reach the
        # end of the iterable before going through max_len elements, then
        # yield any last elements that were built up and get out.
        chunk = []
        for _ in range(max_len):
            try:
                chunk.append(next(source))
            except StopIteration:
                if chunk: yield chunk
                no_more = True
                break

        if no_more:
            break

        # If we were able to build up a full chunk, yield it and loop
        # again.
        yield chunk


class ShareaboutsTool (object):
    def __init__(self, host, auth=None):
        self.api_root = host + '/api/v2/'
        self.places_url_template = self.api_root + '%s/datasets/%s/places'
        self.submissions_url_template = self.api_root + '%s/datasets/%s/submissions'
        self.snapshots_url_template = self.api_root + '%s/datasets/%s/%s/snapshots'

        self.api = ShareaboutsApi(self.api_root)
        if auth:
            self.api.authenticate_with_basic(*auth)  # <-- (username, password)
            self.fetch_params = {
                'include_private': True,
                'include_invisible': True
            }
        else:
            self.fetch_params = {}

    def convert_times(self, data, timezone):
        from shareabouts.models import ShareaboutsModel, ShareaboutsCollection
        from dateutil import parser

        if isinstance(data, (list, ShareaboutsCollection)):
            for elem in data:
                self.convert_times(elem, timezone)
            return data

        elif isinstance(data, (dict, ShareaboutsModel)):
            for key in data:
                value = data[key]
                data[key] = self.convert_times(value, timezone)
            return data

        elif isinstance(data, str_base):
            try:
                dt = parser.parse(data)
            except (TypeError, ValueError):
                return data
            except OverflowError:  # <-- a phone number with no dashes was causing an overflow error???
                return data
            if dt.tzinfo:
                dt = dt.astimezone(timezone)
                data = dt.isoformat()
            return data

        else:
            return data

    def get_places(self, owner, dataset):
        places_url = self.places_url_template % (owner, dataset)

        # Load all of the dataset's places into memory, mapped by their ids
        print('Loading places from %s...' % places_url, file=sys.stderr)
        num_loaded_pages = 0

        places = self.api.account(owner).dataset(dataset).places

        for places_page in places.fetch_all(**self.fetch_params):
            num_loaded_pages += 1
            print('\r...loaded page %s of %s  ' % (num_loaded_pages, places.page_count), end='', file=sys.stderr)
        print(file=sys.stderr)

        return list(places)

    def get_snapshot(self, owner, dataset, set_name='places', format='json', force_new=False, params=None):
        snapshots_url = (self.snapshots_url_template % (owner, dataset, set_name))
        if params is None: params = self.fetch_params
        send_data = params.copy()

        snapshots = None
        if not force_new:
            # Check to see whether we already have a snapshot
            try: from urllib.parse import urlencode
            except: from urllib import urlencode

            print('Checking for existing %s snapshots from %s with params %s...' % (set_name, snapshots_url, params), file=sys.stderr)
            response = self.api.send('GET', snapshots_url + '?' + urlencode(send_data))

            assert response.status_code != 404, 'Dataset %s/%s cannot be found' % (owner, dataset)
            if response.status_code != 200:
                raise Exception('Unexpected response from %s snapshot for dataset %s/%s: %s, %s' % (set_name, owner, dataset, response.status_code, response.content))

            try:
                snapshots = response.json()
            except ValueError:
                raise Exception('Unexpected non-JSON content from %s snapshot for dataset %s/%s: %s' % (set_name, owner, dataset, response.content))

        if snapshots:
            # If there are snapshots, get the one with the latest requested
            # datetime.
            snapshot = max(snapshots, key=lambda sn: sn.get('requested_at'))
            print('Using existing %s snapshot from %s taken at %s...' % (set_name, snapshots_url, snapshot['requested_at']), file=sys.stderr)

            try:
                snapshot_url = snapshot['url']
            except KeyError:
                raise Exception('%s snapshot for dataset %s/%s does not have a URL: %s' % (set_name, owner, dataset, snapshot))
        else:
            # If we don't have any snapshots (or we explicitly want a new one),
            # request that one be created and wait.
            print('Requesting new %s snapshot from %s...' % (set_name, snapshots_url,), file=sys.stderr)
            response = self.api.send('POST', snapshots_url, data=send_data)

            assert response.status_code != 404, 'Dataset %s/%s cannot be found' % (owner, dataset)
            if response.status_code not in (200, 201, 202):
                raise Exception('Unexpected response from %s snapshot for dataset %s/%s: %s, %s' % (set_name, owner, dataset, response.status_code, response.content))

            try:
                snapshot_url = response.json()['url']
            except ValueError:
                raise Exception('Unexpected non-JSON content from new %s snapshot request for dataset %s/%s: %s' % (set_name, owner, dataset, response.content))
            except KeyError:
                raise Exception('Unexpected JSON content from new %s snapshot request for dataset %s/%s (no URL): %s' % (set_name, owner, dataset, response.content))

        snapshot_url += '.' + format
        first_check = True
        while True:
            # Forever, try to download the snapshot.
            response = requests.get(snapshot_url)

            if response.status_code == 503:
                if first_check:
                    print('Waiting for %s snapshot from %s...' % (set_name, snapshots_url,), file=sys.stderr, end='')
                    first_check = False
                else:
                    print('.', file=sys.stderr, end='')
                time.sleep(2)

            elif response.status_code == 200:
                if not first_check: print('', file=sys.stderr)
                return response.content

            else:
                raise Exception('Unexpected response from %s snapshot for dataset %s/%s: %s, %s' % (set_name, owner, dataset, response.status_code, response.content))

    def get_submissions(self, owner, dataset):
        dataset = self.api.account(owner).dataset(dataset)
        dataset.fetch()

        all_submissions = []

        for set_name in dataset.get('submission_sets'):
            submissions = dataset.submissions.in_set(set_name)

            # Load all of the dataset's places into memory, mapped by their ids
            print('Loading submissions from %s...' % submissions.url(), file=sys.stderr)
            num_loaded_pages = 0

            submissions = dataset.submissions.in_set(set_name)

            for page in submissions.fetch_all(**self.fetch_params):
                num_loaded_pages += 1
                print('\r...loaded page %s of %s  ' % (num_loaded_pages, submissions.page_count), end='', file=sys.stderr)
            print(file=sys.stderr)

            all_submissions.extend(submissions)

        return all_submissions

    def get_source_place_map(self, all_places, mapped_id_field='_imported_id'):
        mapped_places = {}

        for place in all_places:
            # If a place has a field that matches the id_field_name, assume
            # that it corresponds to the ID of the place from the imported
            # data.
            if mapped_id_field in place:
                source_id = place[mapped_id_field]
                mapped_places[source_id] = place

        print('\nSaw %s places, with %s having come from somewhere else.' % (len(all_places), len(mapped_places)), file=sys.stderr)
        return mapped_places

    def updated_from_geojson(self, mapped_places, source_filename, source_id_field=None, mapped_id_field='_imported_id', include_fields=set(), mapped_fields={}, default_values={}):
        print('Loading places from %s...' % source_filename, file=sys.stderr)

        # Load the new places from the file
        loaded_places = []

        with open(source_filename) as geojson_file:
            loaded_featureset = json.load(geojson_file)

            assert 'features' in loaded_featureset
            for feature in loaded_featureset['features']:

                try:
                    # Take note of the source data's ID
                    if source_id_field:
                        feature_id = feature['properties'][source_id_field]
                    else:
                        feature_id = feature['id']
                except KeyError:
                    print('\nFound a place that does not have an ID field: %s\n\nSkip it? (y|n): ' % (feature,), file=sys.stderr, end='')
                    skipit = cli_input()
                    if skipit.lower() == 'y':
                        continue
                    else:
                        print('Bailing.', file=sys.stderr)
                        sys.exit(0)

                # Make a new "place" out of a copy of the source data
                place = feature.copy()

                # Keep only fields we want
                if include_fields:
                    for field in list(place['properties'].keys()):
                        if field not in include_fields:
                            del place['properties'][field]

                # Use the source ID to match any existing data, if it exists
                if feature_id in mapped_places:
                    old_place = mapped_places[feature_id]
                    if 'id' in old_place:
                        place['id'] = old_place['id']
                    else:
                        del place['id']
                    place['properties']['url'] = old_place['url']
                else:
                    place.pop('id')

                # Apply field mappings
                for field_name in list(place['properties'].keys()):
                    if field_name in mapped_fields:
                        place['properties'][mapped_fields[field_name]] = place['properties'][field_name]
                place['properties'][mapped_id_field] = feature_id

                # Add any extra data
                for field_name, value in default_values.iteritems():
                    if field_name not in place['properties']:
                        place['properties'] = value

                loaded_places.append(place)

        print('%s place(s) loaded, with %s having been seen before.' % (len(loaded_places), len([place for place in loaded_places if 'url' in place['properties']])), file=sys.stderr)
        return loaded_places

    def updated_from_csv(self, mapped_places, source_filename, source_id_field=None, mapped_id_field='_imported_id', include_fields=set(), mapped_fields={}, default_values={}):
        print('Loading places from %s...' % source_filename, file=sys.stderr)

        # CSVs only know about strings, so make sure places are mapped by
        # strings.
        for map_key in mapped_places.keys():
            mapped_places[str(map_key)] = mapped_places.pop(map_key)

        # Load the new places from the file
        loaded_places = []

        with open(source_filename) as csv_file:
            reader = csv.reader(csv_file)
            headers = None

            for row in reader:
                if headers is None:
                    headers = row
                    continue
                properties = dict(zip(headers, row))

                # Take note of the source ID
                try:
                    feature_id = properties[source_id_field or 'id']
                except KeyError:
                    raise Exception('You must include in "id" column in your CSV file.')

                # Make a new "place" from the source data
                place = {
                    'properties': properties,
                    'id': feature_id,
                    'type': 'Feature'
                }

                # Special case for lat/lng
                if 'lat' in properties and 'lon' in properties:
                    place['geometry'] = {
                        'type': 'Point',
                        'coordinates': [float(properties.pop('lon')), float(properties.pop('lat'))]
                    }

                # Keep only fields we want
                if include_fields:
                    for field in place['properties'].keys():
                        if field not in include_fields:
                            del place['properties'][field]

                # Use the source ID to match and existing data
                if feature_id in mapped_places:
                    old_place = mapped_places[feature_id]
                    place['id'] = old_place['id']
                    place['properties']['url'] = old_place['url']
                else:
                    place.pop('id')

                # Apply field mappings
                for field_name in list(place['properties'].keys()):
                    if field_name in mapped_fields:
                        place['properties'][mapped_fields[field_name]] = place['properties'][field_name]
                place['properties'][mapped_id_field] = feature_id

                # Add any extra data
                for field_name, value in default_values.iteritems():
                    if field_name not in place['properties']:
                        place['properties'] = value

                loaded_places.append(place)

        print('%s place(s) loaded, with %s having been seen before.' % (len(loaded_places), len([place for place in loaded_places if 'url' in place['properties']])), file=sys.stderr)
        return loaded_places

    def save_places(self, owner, dataset, dataset_key, loaded_places, callback, silent=True, create=True, update=True):
        # Upload the places, with PUT if they have a URL, otherwise with POST
        places_url = self.places_url_template % (owner, dataset)

        # Create threads in chunks so that we don't run out of available
        # threads.
        for chunk_of_places in chunks_of(loaded_places, 100):
            save_threads = []
            for place in chunk_of_places:
                if (update and 'url' in place['properties']) or \
                   (create and 'url' not in place['properties']):
                    thread = UploadPlaceThread(place, places_url, dataset_key, callback,
                        silent=silent, create=create, update=update)
                    thread.start()
                    save_threads.append(thread)

            for thread in save_threads:
                thread.join()

    def delete_places(self, owner, dataset, dataset_key, loaded_places, callback):
        # Create threads in chunks so that we don't run out of available
        # threads.
        for chunk_of_places in chunks_of(loaded_places, 100):
            delete_threads = []
            for place in chunk_of_places:
                thread = DeletePlaceThread(place, dataset_key, callback)
                thread.start()
                delete_threads.append(thread)

            for thread in delete_threads:
                thread.join()


class UploadPlaceThread (threading.Thread):
    finite_threads = threading.BoundedSemaphore(value=4)

    def __init__(self, place, places_url, dataset_key, callback, silent=True, create=True, update=True):
        self.place = place
        self.places_url = places_url
        self.dataset_key = dataset_key
        self.callback = callback

        self.silent = silent
        self.create = create
        self.update = update

        super(UploadPlaceThread, self).__init__()

    def create_place(self):
        return requests.post(
            self.places_url,
            data=json.dumps(self.place),
            headers={
                'content-type': 'application/json',
                'x-shareabouts-silent': 'true' if self.silent else 'false',
                'x-shareabouts-key': self.dataset_key,
                'x-csrftoken': '123'
            },
            cookies={'csrftoken': '123'}
        )

    def update_place(self):
        place_url = self.place['properties']['url']
        return requests.put(
            place_url,
            data=json.dumps(self.place),
            headers={
                'content-type': 'application/json',
                'x-shareabouts-silent': 'true' if self.silent else 'false',
                'x-shareabouts-key': self.dataset_key,
                'x-csrftoken': '123'
            },
            cookies={'csrftoken': '123'}
        )

    def run(self):
        place = self.place
        with UploadPlaceThread.finite_threads:
            retry_timeout = 1

            while True:
                try:
                    if 'url' in self.place['properties']:
                        place_response = self.update_place()
                    else:
                        place_response = self.create_place()
                    # place.save()

                except requests.exceptions.ConnectionError:
                    print('Failed to upload place; sleeping for %s seconds' % retry_timeout, file=sys.stderr)
                    time.sleep(retry_timeout)
                    if retry_timeout < 30:
                        retry_timeout *= 2

                else:
                    break

            self.callback(place, place_response)


class DeletePlaceThread (threading.Thread):
    finite_threads = threading.BoundedSemaphore(value=4)

    def __init__(self, place, dataset_key, callback):
        self.place = place
        self.dataset_key = dataset_key
        self.callback = callback
        super(DeletePlaceThread, self).__init__()

    def run(self):
        place = self.place
        with DeletePlaceThread.finite_threads:
            # place.destroy()

            place_url = place.get('url')
            assert place_url is not None
            place_response = requests.delete(
                place_url,
                headers={
                    'content-type': 'application/json',
                    'x-shareabouts-silent': 'true',
                    'x-shareabouts-key': self.dataset_key,
                    'x-csrftoken': '123'
                },
                cookies={'csrftoken': '123'}
            )

            self.callback(place, place_response)
