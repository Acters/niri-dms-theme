# SPDX-License-Identifier: MIT
"""The few XDG locations used by this theme."""
import os
from pathlib import Path
import re

def context(home=None):
    explicit=home is not None
    home=Path(home).expanduser().absolute() if explicit else Path.home()
    ctx={'HOME':str(home)}
    for key,default in (('CONFIG_HOME','.config'),('DATA_HOME','.local/share'),('STATE_HOME','.local/state'),('CACHE_HOME','.cache')):
        value=None if explicit else os.environ.get('XDG_'+key)
        ctx[key]=str(Path(value) if value and Path(value).is_absolute() else home/default)
    ctx['PROFILE_CONFIG']=str(Path(ctx['CONFIG_HOME'])/'niri-dms-theme')
    ctx['PROFILE_DATA']=str(Path(ctx['DATA_HOME'])/'niri-dms-theme')
    ctx['PLUGIN_ROOT']=str(Path(ctx['PROFILE_DATA'])/'qt-plugins')
    ctx['PROFILE_SHARE']=str(Path(ctx['PROFILE_DATA'])/'share')
    data='/usr/local/share:/usr/share' if explicit else os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    config='/etc/xdg' if explicit else os.environ.get('XDG_CONFIG_DIRS') or '/etc/xdg'
    ctx['MERGED_DATA_DIRS']=':'.join(dict.fromkeys([ctx['PROFILE_SHARE'],*[p for p in data.split(':') if Path(p).is_absolute()]]))
    ctx['MERGED_CONFIG_DIRS']=':'.join(dict.fromkeys([str(Path(ctx['PROFILE_CONFIG'])/'shared'),*[p for p in config.split(':') if Path(p).is_absolute()]]))
    return ctx

def render(text,ctx):
    text=re.sub(r'@([A-Z][A-Z0-9_]*)@',lambda m:ctx.get(m[1],m[0]),text)
    if re.search(r'@[A-Z][A-Z0-9_]*@',text) or '\x00' in text:
        raise ValueError('Unresolved theme path')
    return text
