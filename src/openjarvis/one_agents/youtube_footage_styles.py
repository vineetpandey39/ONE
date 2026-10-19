"""Reusable weekday callouts over footage, without full-screen typography cards."""


def callout_style(family):
    profiles = {
        'travel-dossier': {'font':'consolab.ttf','size':40,'x':'70','y':'h-145','color':'white','box':'black@0.6','max_chars':62},
        'cinematic-clean': {'font':'arial.ttf','size':42,'x':'70+40*exp(-6*(t-0.3))','y':'h-125','color':'white','box':'black@0.45','max_chars':64},
        'editorial-punch': {'font':'georgiab.ttf','size':44,'x':'w-text_w-75+80*exp(-8*(t-0.3))','y':'100','color':'white','box':'black@0.5','max_chars':54},
        'kinetic-type': {'font':'arialbd.ttf','size':64,'x':'(w-text_w)/2','y':'h-200+20*exp(-8*t)','color':'white','box':'black@0.45','max_chars':42},
        'motion-lab': {'font':'consola.ttf','size':38,'x':'w-text_w-90+8*sin(t*3)','y':'h-180+3*cos(t*2)','color':'cyan','box':'black@0.55','max_chars':60},
    }
    if family not in profiles:
        raise ValueError('Unknown shared weekday format')
    return profiles[family].copy()


def callout_filter(textfile, family):
    style=callout_style(family)
    font='C\\:/Windows/Fonts/'+style['font']
    path=textfile.as_posix().replace(':','\\:')
    return (f",drawtext=fontfile='{font}':textfile='{path}':fontsize={style['size']}:fontcolor={style['color']}:"
        f"x='{style['x']}':y='{style['y']}':alpha='min(1,(t-0.3)/0.3)':box=1:boxcolor={style['box']}:"
        "boxborderw=18:enable='between(t,0.3,2.4)'")
