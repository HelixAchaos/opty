from settings_shid import get_targets, get_rules, get_settings

settings = get_settings('settings.json')
rules = get_rules(settings['rules'])
targets = get_targets(settings['targets'])
version = settings['version']

# lazy = get_targets(settings['lazy?'])

