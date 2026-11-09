"""Data-only devotional extensions to the installed Motion V3 pipeline."""
PRESETS = {
 'SHIVA_COSMIC': {'deity':'Shiva','color':'#75CFFF','accent':'#D5B877','motif':'orbit','bpm':72,'fog':0.12,'petals':False,'lightning':True},
 'DURGA_SHAKTI': {'deity':'Durga','color':'#FF744B','accent':'#FFD28A','motif':'soft-particles','bpm':96,'fog':0.07,'petals':True,'lightning':True},
 'KRISHNA_VRINDAVAN': {'deity':'Krishna','color':'#76DCC1','accent':'#C8B6FF','motif':'soft-particles','bpm':68,'fog':0.14,'petals':True,'lightning':False},
 'HANUMAN_DIVINE_POWER': {'deity':'Hanuman','color':'#FF9B46','accent':'#FFF1BC','motif':'orbit','bpm':100,'fog':0.08,'petals':False,'lightning':True},
 'LAKSHMI_GOLDEN': {'deity':'Lakshmi','color':'#FFD578','accent':'#FFA9CE','motif':'soft-particles','bpm':76,'fog':0.08,'petals':True,'lightning':False},
 'GANESH_FESTIVAL': {'deity':'Ganesh','color':'#FF8C57','accent':'#FFE79B','motif':'soft-particles','bpm':112,'fog':0.06,'petals':True,'lightning':False},
 'RAM_AYODHYA': {'deity':'Ram','color':'#FFCC7A','accent':'#B5D8FF','motif':'contour','bpm':80,'fog':0.10,'petals':True,'lightning':False},
 'SARASWATI_SERENE': {'deity':'Saraswati','color':'#E3EDFF','accent':'#F3DDA9','motif':'soft-particles','bpm':60,'fog':0.12,'petals':True,'lightning':False},
}
VOCAL_STYLES = {
 'powerful_male': {'direction':'resonant male devotional singing, precise Hindi and Sanskrit diction, mridangam and damru', 'tts_voice_id':'xXkBR6e4rJbGFb4Y0JLx'},
 'soft_male': {'direction':'gentle male bhajan singing, tanpura, bansuri, restrained tabla', 'tts_voice_id':'xXkBR6e4rJbGFb4Y0JLx'},
 'female_devotional': {'direction':'warm female devotional singing, veena, tanpura and soft tabla', 'tts_voice_id':'xccfcojYYGnqTTxwZEDU'},
 'chorus': {'direction':'reverent layered devotional choir, clear unison lyrics, call and response', 'tts_voice_id':None},
 'instrumental_meditation': {'direction':'instrumental meditation, no voices, tanpura, bansuri, sparse bells', 'tts_voice_id':None},
 'energetic_festival': {'direction':'joyous devotional ensemble, dhol, mridangam, cymbals, energetic sung chorus', 'tts_voice_id':'xXkBR6e4rJbGFb4Y0JLx'},
}

VISUAL_BIBLE = ('Respectful cinematic devotional painting of Shiva meditating at Mount Kailash. '
 'Consistent calm face, ash-blue skin, matted hair with crescent moon, visible third eye, rudraksha beads, '
 'serpent around neck, modest traditional seated attire. Two anatomically correct arms. '
 'Trident and damru beside him; moonlit snowy peaks, deep midnight blue with restrained warm gold. '
 'Sacred iconography, no modern objects, no logos, no text, no watermark. '
 'Wide 16:9 composition, subject within central 35 percent for vertical crop; generous negative space. ')

def voice_for(config, deity, composition, style):
    """Narration ID configuration is deliberately separate from Music's singer direction."""
    overrides = config.get('voice_overrides', {})
    return overrides.get(deity,{}).get(composition,{}).get(style, VOCAL_STYLES[style]['tts_voice_id'])
