"""Is this word Swahili or Sheng? A word list plus the shape of Swahili verbs.

The ears test scores each speech model on the Swahili and Sheng words alone
(asr/bench.py). That needs a decent tagger, not a perfect one: common
Swahili/Sheng words, and verb forms (subject + tense prefix, vowel ending:
"anasema", "tutaenda", "nimeona") catch most of it. Words that are also
English ("pole", "tuna", "vile", "wake") are never counted, and neither are
spellings Swahili doesn't use (q, x, a lone c, clusters like "bl", "tr").
"""

from __future__ import annotations

import re

from ..spec.glossary import norm

WORDS = frozenset("""
mimi wewe yeye sisi nyinyi ninyi wao mi
huyu huyo yule hawa hao wale hii hiyo ile hizi hizo zile hili hilo lile haya hayo yale
hiki hicho kile hivi hivyo huu huo ule hapa hapo huku huko kule humu humo mle
na ya wa za la cha vya kwa ni si tu pia lakini ama au kama kwamba ili ingawa hata bali wala
basi sasa halafu kisha tena yaani ati eti ndio ndiyo hapana sawa kweli sana zaidi kabisa bado
tayari labda pengine mpaka hadi tangu kwenye katika juu chini ndani nje mbele nyuma kati
karibu mbali pamoja bila kuhusu badala kwanza mwisho leo kesho jana wakati siku mwaka saa
nini nani wapi lini vipi gani ngapi je kwani aje
kuwa kuna kuja kwenda kusema kufanya kujua kuona kupenda kuomba kusoma kuamini kusikia
kupata kutaka kuweza kupa kuishi kufa kuokoka kusifu kuabudu kutoa kulipa kuanza kumaliza
kukaa kusimama kurudi kufika kutembea kuongea kuambia kuuliza kujibu kuandika kuimba
kucheza kula kunywa kulala kuamka kufundisha kujifunza kukosa kukosana kuskia kuenda
niko uko yuko tuko mko wako iko ndiko ndipo nina una ana tuna mna wana sina huna hana
hatuna hamna hawana sijui hujui hajui najua nataka sitaki nasema sema semeni useme
ebu hebu tusome tuombe tumwombe twende njoo enda nenda ona angalia sikiza sikia ngoja subiri
fanya jua amka simama keti omba soma imba
mungu yesu kristo bwana roho mtakatifu asifiwe amina baraka utukufu imani neno maneno
maombi ombi injili kanisa mchungaji nabii mtume malaika shetani dhambi wokovu msalaba
damu upendo neema rehema huruma uzima milele mbinguni duniani dunia ufalme baba mwana mama
ndugu dada kaka wapendwa mpendwa watu mtu kitu vitu maisha moyo mioyo nguvu amani furaha
ukweli haki sifa shukrani asante mwokozi muumba mbingu nchi
moja mbili tatu nne tano sita saba nane tisa kumi ishirini thelathini mia elfu
mzuri nzuri vizuri mbaya kubwa mkubwa ndogo mdogo kidogo mingi wengi nyingi yote wote zote
kila mwingine wengine nyingine kingine mpya rahisi ngumu
yangu wangu zangu changu yako wako zako chako yake zake chake yetu wetu yenu wenu yao
poa msee wasee manze maze buda mathe fathe chali mbogi ngori ganji mulla keja mtaa rada
fiti noma niaje mambo freshi shida enyewe mzae beshte msupa manzi dame karao kanjo nduthi
wueh venye vako
""".split())

# Also English: never counted, whatever the list or the verb shape says.
ENGLISH = frozenset("""
pole tuna vile wake form mat dem doh mob alike alive alibi alienate inane akimbo analyse analyze
""".split())

# Subject prefix + tense marker + root + final vowel: ni-na-sema, tu-ta-enda,
# a-me-ona, wa-li-kuja; negatives ha-tu-…, si-…, "don't" u-si-… (Sheng puts
# English roots there too: "usiignore"); infinitives ku-…. Not a-si-: "aside".
_VERB = re.compile(
    r"^(?:(?:ni|u|a|tu|m|mu|wa|i|ki|vi|li|zi|ha|hatu|ham|hawa|si|hu)(?:na|li|ta|me|nge|ngali|ka|ki)"
    r"|(?:ni|u|tu|m|wa)si|ku)[a-z]{2,}[aeiou]$"
)
_NOT_SWAHILI_SPELLING = re.compile(r"[qx]|c(?!h)|bl|pl|fl|gl|sl|br|cr|dr|gr|pr|tr|wr|st|sp|ll|ss|tt|ff|pp|rr|dd|bb")


def is_swahili(word: str) -> bool:
    w = norm(word).replace("'", "")
    if not w or " " in w or w in ENGLISH:
        return False
    if w in WORDS:
        return True
    return len(w) >= 5 and not _NOT_SWAHILI_SPELLING.search(w) and bool(_VERB.match(w))


def share(text: str) -> float:
    """Fraction of the words in `text` that are Swahili or Sheng."""
    words = norm(text).split()
    return sum(map(is_swahili, words)) / len(words) if words else 0.0
