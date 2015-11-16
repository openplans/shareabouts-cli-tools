from collections import defaultdict
from datetime import datetime
from pybars import strlist
from pybars._compiler import resolve, _if, is_dictlike, is_iterable


# Handlebars helpers
def _title(this, string):
    return string.title()

def _underline(this, string, char='-'):
    return char*len(string)

def _first_of(this, *values):
    for value in values:
        if value:
            return value

def _each_sorted(this, options, context, reverse=False):
    """
    A version of the each helper where dicts' keys are sorted
    """
    if not context:
        return options['inverse'](this)

    cond_reversed = reversed if reverse else (lambda x: x)

    result = strlist()
    if is_dictlike(context):
        for key, local_context in cond_reversed(sorted(context.items())):
            result.grow(options['fn'](local_context, key=key))
    elif is_iterable(context):
        for index, local_context in enumerate(context):
            result.grow(options['fn'](local_context, index=index))
    else:
        return options['inverse'](this)
    return result

def _if_changed(this, options, var, val=None):
    if not hasattr(this.context, '_memo'):
        this.context._memo = {}

    val = val or resolve(this, *var.split('.'))
    if var not in this.context._memo:
        this.context._memo[var] = val
        changed = True
    else:
        changed = (this.context._memo[var] == val)
        this._memo[var] = val

    if changed:
        return options['fn'](this)
    else:
        return options['inverse'](this)

def _if_datetime_changed(this, options, var, format):
    val = resolve(this, *var.split('.'))
    dt_formatted = _format(this, val, format)
    return _if_changed(this, options, var + '_formatted_' + format, dt_formatted)

def _quoted(this, value):
    if value:
        return strlist(['"', value.replace('\\', '\\\\').replace('"', '\\"'), '"'])

def _format(this, value, format):
    if value:
        try:
            dt = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
            return dt.strftime(format)
        except ValueError:
            pass
    return value

# Usage: {{#filter_by [collection] attribute value}}
def _filter_by(this, options, *args):
    # If there are three arguments, the first is the set of things to be
    # filtered.
    if len(args) == 3:
        iterable, attr_name, filter_val = args

    # If there are only two, `this` is assumed to be the set of things to
    # filter.
    elif len(args) == 2:
        attr_name, filter_val = args
        iterable = this

    # Any other number of args is an error.
    else:
        raise ValueError('filter takes either two or three arguments.')

    # Check the options for a function that generates a filter criteria. The
    # function should take three parameters (an element, the name of an
    # attribute, and a value to filter on) and generate a filter criteria. By
    # default, filter_condition returns a function that checks equality.
    filter_condition = options.get(
        'filter_condition',
        lambda elem, attr, val: resolve(elem, *attr.split('.')) == val
    )

    filtered_context = filter(lambda elem: filter_condition(elem, attr_name, filter_val), iterable)

    if len(filtered_context) == 0:
        return options['inverse'](this)

    return options['fn'](filtered_context)

# Usage: {{#filter_by_any collection attribute value1 [value2 ...] }}
def _filter_by_any(this, options, iterable, attr_name, *filter_vals):
    options['filter_condition'] = lambda elem, attr, val: resolve(elem, *attr.split('.')) in val
    return _filter_by(this, options, iterable, attr_name, set(filter_vals))

# Usage: {{percentage_of [collection] attribute value}}
def _percentage_of(this, *args):
    # If there are three arguments, the first is the set of things to be
    # filtered.
    if len(args) == 3: iterable = args[0]
    # If there are only two, `this` is assumed to be the set of things to
    # filter.
    elif len(args) == 2: iterable = this
    # Any other number of args is an error.
    else: raise ValueError('percentage_of takes either two or three arguments.')

    def calculate_percentage(filtered_context):
        try:
            return 100.0 * len(filtered_context) / len(iterable)
        except ZeroDivisionError:
            return 0

    options = {'fn': calculate_percentage, 'inverse': (lambda _: 0)}
    percentage = _filter_by(this, options, *args)
    return int(round(percentage))

def _sort_by(this, options, *args):
    # If there's one argument, it's the sorting attribute name, and this will
    # be used as the context (iterable).
    if len(args) == 1:
        attr_name = args[0]
        iterable = this

    # If there are two arguments, the first is the context, the second if the
    # sorting argument.
    else:
        iterable, attr_name = args

    # Check the options for the function that generates an sort key. The
    # function should take two parameters (an element and the name of an
    # attribute) and generate a sort key.
    sort_key_maker = options.get(
        'sort_key_maker',
        lambda elem, attr: resolve(elem, *attr.split('.'))
    )

    reverse = False
    if attr_name[0] == '-':
        reverse = True
        attr_name = attr_name[1:]

    sorted_context = sorted(iterable, key=lambda elem: sort_key_maker(elem, attr_name))
    if reverse:
        sorted_context = reversed(sorted_context)
    return options['fn'](sorted_context)

def _group_by(this, options, *args):
    # If there's one argument, it's the grouping attribute name, and this will
    # be used as the context (iterable).
    if len(args) == 1:
        attr_name = args[0]
        iterable = this

    # If there are two arguments, the first is the context, the second if the
    # grouping argument.
    else:
        iterable, attr_name = args

    # Check the options for the function that generates an group key. The
    # function should take two parameters (an element and the name of an
    # attribute) and generate a group key.
    group_key_maker = options.get(
        'group_key_maker',
        lambda elem, attr: resolve(elem, *attr.split('.'))
    )

    reverse = False
    if attr_name[0] == '-':
        reverse = True
        attr_name = attr_name[1:]

    grouped_context = defaultdict(list)
    for elem in iterable:
        group_key = group_key_maker(elem, attr_name)
        try:
            grouped_context[group_key].append(elem)
        except TypeError as e:
            raise TypeError('Attribute {!r} resolved to {}'.format(attr_name, e))

    return _each_sorted(this, options, grouped_context, reverse)

def _group_by_date(this, options, *args):
    # The group key should only take in to accound the first 10 characters of
    # the given attribute, as the first 10 characters in an ISO8601 formatted
    # date/time string represent the date portion.
    options['group_key_maker'] = lambda elem, attr: resolve(elem, *attr.split('.'))[:10]
    return _group_by(this, options, *args)

def _if_gte(this, options, val1, val2):
    return _if(this, options, lambda _: val1 >= val2)

def _if_lte(this, options, val1, val2):
    return _if(this, options, lambda _: val1 <= val2)

def _if_equal(this, options, val1, val2):
    return _if(this, options, lambda _: val1 == val2)

def _if_any(this, options, *values):
    return _if(this, options, any(values))

def _if_all(this, options, *values):
    return _if(this, options, all(values))

def _with(this, options, local_context):
    return options['fn'](local_context)

def _length(this, *args):
    if len(args) == 1:
        context = args[0]
    else:
        context = this

    if context is None:
        return 0

    try:
        return len(context)
    except TypeError:
        return len(context.context)

def _lookup(this, *args):
    if len(args) == 2:
        context, key = args
    elif len(args) == 1:
        context = this
        key = args[0]
    else:
        raise ValueError('lookup expects 1 or 2 arguments.')

    try:
        return context[key]
    except (KeyError, IndexError):
        return None

def _replace(this, text, old, new):
    return text.replace(old, new)

helpers = {
    'title': _title,
    'underline': _underline,
    'first_of': _first_of,
    'each_sorted': _each_sorted,
    'if_changed': _if_changed,
    'if_datetime_changed': _if_datetime_changed,
    'quoted': _quoted,
    'format': _format,
    'filter_by': _filter_by,
    'filter_by_any': _filter_by_any,
    'percentage_of': _percentage_of,
    'sort_by': _sort_by,
    'group_by': _group_by,
    'group_by_date': _group_by_date,
    'if_lte': _if_lte,
    'if_gte': _if_gte,
    'if_equal': _if_equal,
    'if_any': _if_any,
    'if_all': _if_all,
    'lookup': _lookup,
    'with': _with,
    'length': _length,
    'replace': _replace,
}


if __name__ == '__main__':
    from nose.tools import assert_equal

    # Check that _percentage_of works
    items = [{'a': 1}, {'a': 1}, {'a': 2}]
    p = _percentage_of(items, 'a', 1)
    assert_equal(p, 67)
    p = _percentage_of(items, 'a', 2)
    assert_equal(p, 33)
    p = _percentage_of(items, 'a', 3)
    assert_equal(p, 0)

    # Check that _filter_by works
    options = {'fn': (lambda x: (True, x)), 'inverse': (lambda x: (False, x))}
    items = [{'a': 1, 'b': 1}, {'a': 1, 'b': 2}, {'a': 2, 'b': 3}]
    r = _filter_by_any({}, options, items, 'b', 1, 2)
