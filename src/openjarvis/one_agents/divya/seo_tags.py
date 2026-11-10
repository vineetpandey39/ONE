"""Unicode-preserving devotional tags with YouTube's quoted-tag budget."""
import unicodedata

def tag_characters(tags):
    return sum(len(t) + (2 if ' ' in t else 0) for t in tags) + max(0, len(tags)-1)

def valid_tags(tags, limit=500):
    result=[]
    seen=set()
    for raw in tags:
        # Combining marks are essential Hindi vowels, anusvara and virama.
        tag=unicodedata.normalize('NFC',str(raw))
        tag=''.join(c if unicodedata.category(c)[0] in 'LMN' or c in " -'." else ' ' for c in tag)
        tag=' '.join(tag.split()).strip(' .-')
        if len(tag)<2 or tag.casefold() in seen:
            continue
        if tag_characters(result+[tag])<=limit:
            result.append(tag);seen.add(tag.casefold())
    return result
