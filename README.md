shareabouts-cli-tools
=====================

For uploading places to a dataset, after you checkout shareabouts-cli-tools, you can run the upload script like:

`./upload.py <config_file>`

where config is a json file in the templates folder.

In your config, set the owner, dataset, key, and source_file, and possibly the fields.

If you want to use all the fields, then just omit the fields value completely.

When uploading point data from csv, make sure you have fields for `id` (must be numeric only), `lat`, `lon`, and `location_type`.

