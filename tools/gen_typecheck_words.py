"""Regenerate src/fastprompter/core/typecheck_words.py.

The shipped English dictionary is built from two sources:

1. The repository's own English text (README, guides, wiki, changelog, the
   English i18n master) — a few thousand real, in-domain words.
2. A curated list of everyday English words and contractions below, so the
   dictionary covers ordinary typing, not just the app's vocabulary.

Run from the repo root:  uv run python tools/gen_typecheck_words.py

The output is a single whitespace-joined string literal (compressed) that
the typecheck module splits at load time. A word is kept only if it is
pure ASCII letters, at least two characters, and appears often enough (or is
in the curated list, which is always kept).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "fastprompter" / "core" / "typecheck_words.py"

SOURCES = [
    "README.md",
    "GUIDE_EN.md",
    "CHANGELOG.md",
    "docs/wiki/Architecture-Overview.md",
    "docs/wiki/Configuration.md",
    "docs/wiki/Core-API-and-Classes.md",
    "docs/wiki/Deployment-Guide.md",
    "docs/wiki/Home.md",
    "docs/wiki/Keyboard-Shortcuts-and-Cheatsheet.md",
    "docs/wiki/Module-Structure.md",
    "docs/wiki/Plugin-and-Skill-Development.md",
    "docs/wiki/README.md",
    "docs/wiki/Troubleshooting-and-FAQ.md",
    "docs/wiki/UI-Components.md",
    "docs/wiki/User-Guide.md",
    "docs/wiki/Watcher-Engine-Architecture.md",
    "src/fastprompter/core/i18n/en.py",
]

# Everyday English: common words, contractions and app-domain terms that must
# survive regardless of corpus frequency. Kept deliberately compact but real.
CURATED = """
the be to of and a in that have i it for not on with he as you do at this but
his by from they we say her she or an will my one all would there their what
so up out if about who get which go me when make can like time no just him
know take people into year your good some could them see other than then now
look only come its over think also back after use two how our work first well
way even new want because any these give day most us is are was were been
being has had did done doing does doing going go went gone came come coming
make made making take took taken taking get got getting gotten see saw seen
seeing look looked looking want wanted wanting need needed needing know knew
known knowing think thought thinking work worked working write wrote written
writing read reading speak spoke spoken speaking give gave given giving find
found finding tell told telling ask asked asking call called calling try
tried trying use used using leave left leaving put putting mean meant meaning
keep kept keeping let letting begin began begun beginning seem seemed seeming
help helped helping talk talked talking turn turned turning start started
starting show showed shown showing hear heard hearing play played playing run
ran running move moved moving like liked liking live lived living believe
believed believing hold held holding bring brought bringing happen happened
happening wait waited waiting stand stood standing sit sat sitting walk
walked walking lose lost losing pay paid paying meet met meeting include
included including continue continued continuing set setting learn learned
learning change changed changing lead led leading understand understood
understanding watch watched watching follow followed following stop stopped
stopped create created creating speak spoke spoken read read reading allow
allowed allowing add added adding spend spent spending grow grew grown
growing open opened opening walk walked walking win won winning offer
offered offering remember remembered remembering love loved loving consider
considered considering appear appeared appearing buy bought buying serve
served serving die died dying send sent sending build built building stay
stayed staying fall fell fallen falling cut cutting reach reached reaching
kill killed killing remain remained remaining suggest suggested suggesting
raise raised raising pass passed passing sell sold selling require required
requiring report reported reporting decide decided deciding pull pulled
pulling return returned returning explain explained explaining hope hoped
hoping develop developed developing carry carried carrying break broke
broken breaking receive received receiving agree agreed agreeing support
supported supporting hit hitting produce produced producing eat ate eating
cover covered covering catch caught catching draw drew drawn drawing choose
chose chosen choosing cause caused causing point pointed pointing listen
listened listening realize realized realizing arrive arrived arriving care
cared caring depend depended depending describe described describing drop
dropped dropping push pushed pushing accept accepted accepting protect
protected protecting treat treated treating mention mentioned mentioning
imagine imagined imagining engage engaged engaging hide hid hidden hiding
assume assumed assuming
a lot about above across after afternoon again against age ago agree ahead
air almost alone along already also although always among amount an and
animal another answer any anyone anything anyway anywhere appear apple area
arm army around arrive art ask attack attempt attention aunt autumn away
baby back bad bag ball band bank bar base basic battle be beach bear beat
beautiful beauty because become bed before begin behaviour behind believe
bell belong below belt best better between beyond big bill bird birth bit
bite black blood blow blue board boat body bone book border born borrow
boss both bottle bottom bowl box boy brain branch brave bread break
breakfast bridge bright bring brother brown brush build burn business busy
but butter buy cake call calm camera camp can candle cap capital car card
care careful carry case cat catch cause cell cent centre century certain
chair chance change charge chase cheap check cheese chicken child chin
chocolate choose church circle city class clean clear climb clock close
cloth cloud club coal coast coat coffee coin cold collect college colour
comb come comfort common company compare complete computer condition
connect consider contain continue control cook cool copper copy corn corner
correct cost cotton count country couple course court cover cow crash
create cross crowd cruel cup cut dad dance danger dark date daughter day
dead deal dear death decide deep degree deliver depend describe design desk
develop dictionary die difference different difficult dig dinner direction
dirty discover discuss disease dish distance divide doctor dog dollar door
double doubt down draw dream dress drink drive drop dry duck during dust
each ear early earth east easy eat edge education effect egg eight either
electric elephant else empty end enemy energy engine engineer enjoy enough
enter equal escape even evening event ever every everybody everyone
everything everywhere exact exam example excellent except exchange excited
exercise expect expensive explain eye face fact fail fair fall false family
famous far farm fast fat father fault fear feed feel female fence few field
fierce fight fill film final find fine finger finish fire firm first fish
fit five fix flag flat flight floor flower fly fold follow food foot force
forest forget fork form forward four free freedom freeze fresh friend
friendly from front fruit full fun funny future game garden gas gate gather
general gentle get gift girl give glad glass go goal god gold good
government grass great green grey ground group grow guard guess guide gun
hair half hall hand hang happen happy hard hat hate have head health hear
heart heat heavy height hello help here hero hide high hill history hit
hobby hold hole holiday home honest hope horse hospital hot hotel hour house
however huge human hundred hunt hurry husband ice idea if ill imagine
important improve in include increase industry information inside instead
institute interest into introduce invent invite island it its itself job join
journey joy judge juice jump just keep key kick kid kill kind king kitchen
knee knife knock know lake lamp land language large last late laugh law
lazy lead leaf learn least leave leg lend length less lesson let letter
level library lie life lift light like line lion lip list listen little live
local lock long look lose lot loud love low luck lunch machine main major
make male man many map mark market marry match material matter may me meal
mean measure meat medicine meet member memory men mental mention message
metal method middle milk million mind minute miss mistake mix model modern
moment money month moon more morning most mother mountain mouth move much
music must my name narrow nation nature near nearly neck need needle
neighbour neither nerve net never new news next nice night nine no noise
north nose not note nothing notice noun now number nurse object ocean
of off offer office often oil old on once one only open operate opinion
opportunity or orange order ordinary other our out outside over own page
pain paint pair pan paper parent park part particular party pass past path
patient pattern pause pay peace pen pencil people per perfect perhaps period
person phone photograph piano pick picture piece pig pin pink place plain
plan plane plant plastic plate play please pleasure plenty pocket point
poison police polite poor popular population position possible post potato
pour power practise prepare present press pretty prevent price pride
primary prison private prize probably problem produce programme promise
pronounce protect proud prove provide public pull punish pupil push put
quarter question quick quiet quite radio rain raise rather reach read ready
real reason receive recent record red refuse region remember reply report
respect rest result return rice rich ride right ring rise risk river road
rock roll roof room root rope rose round row rub rule run rush sad safe
sail salt same sand save say science sea search seat second secret see seed
seem sell send sense sentence separate serious serve seven several sex
shadow shake shape share sharp sheep sheet shelf shine ship shirt shock
shoe shop short shoulder shout show shut side sight sign silence silly
silver similar simple since sing sister sit situation six size skill skin
skirt sky sleep slip slow small smell smile smoke snow so soap soft soldier
solid solution solve some somebody someone something sometimes somewhere son
song soon sorry sort sound soup south space speak special speech speed
spell spend spoon sport spread spring square stage stair stamp stand star
start station stay steal steam steel steep step stick still stone stop
store storm story straight strange street strength stretch strike strong
student study subject subtract succeed success such sudden suffer sugar
suggest summer sun supply support sure surface surprise swim sword table
take talk tall taste teach team tear telephone television tell temperature
ten tennis terrible test than thank that the their them then there these
they thick thin thing think third this those though thought thousand three
through throw thus ticket tie time tiny tired to today together tomorrow
tonight too tool tooth top total touch towards town trade train travel tree
trick trip trouble true trust truth try turn twelve twenty twice two type
ugly uncle under understand unit until up upon us use usual valley value
various vegetable very victory view village violent visit voice wait wake
walk wall want war warm wash waste watch water wave way we weak wear weather
week weight welcome well west wet what wheat wheel when where whether which
while whisper white who whole why wide wife wild will win wind window wine
wing winter wire wise wish with without woman wonder wood word work world
worry worse worst worth would wound write wrong wrote yard year yellow yes
yet you young your yours yourself zero zoo
don't can't won't isn't aren't wasn't weren't doesn't didn't hasn't haven't
hadn't shouldn't couldn't wouldn't mustn't needn't let's it's that's what's
here's there's where's how's who's why's i'm i've i'll i'd you're you've
you'll you'd he's he'll he'd she's she'll she'd we're we've we'll we'd
they're they've they'll they'd
silo silos snippet snippets scratchpad scratchpads kanban pomodoro timers
watcher queue prompts prompt clipboard autosave autosaved hotkey hotkeys
sidebar toolbar archive archived checkbox markdown highlighter underline
italics bold folder folders project projects profile profiles theme themes
should would could quickly slowly surely actually really finally probably
possibly completely absolutely definitely certainly clearly simply easily
exactly especially generally immediately recently suddenly eventually
currently obviously seriously carefully quietly happily sadly nicely mostly
nearly almost always never often sometimes usually rarely frequently today
tonight again another between during within without against across around
before behind below beneath beside beyond through throughout toward towards
until upon after above along among because although though unless whether
while whereas despite however therefore moreover furthermore besides instead
otherwise meanwhile then thus hence accordingly nevertheless nonetheless
still yet so such very quite rather fairly pretty somewhat extremely highly
deeply strongly barely hardly merely solely purely truly precisely roughly
approximately opposite similar different same various several multiple
numerous countless many much few little some any every each both neither
either all most least greatest smallest largest biggest highest lowest
oldest youngest newest earliest latest furthest nearest longest shortest
deepest tallest broadest widest thickest thinnest heaviest lightest fastest
slowest simplest hardest easiest strongest weakest cheapest yesterday
tomorrow morning afternoon night midnight noon week year day hour minute
second moment instant period duration length width height depth size
amount number quantity quality value price cost rate speed pace volume
weight mass distance space time place position location site area region
zone district county state country nation city town village capital center
centre middle edge corner side top bottom left right front back inside
outside end start beginning finish complete final initial previous next
last first second third fourth fifth sixth seventh eighth ninth tenth
interesting suggestion quickly
"""


def extract(path: Path) -> set[str]:
    words: set[str] = set()
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return words
    for m in re.finditer(r"[A-Za-z']{2,}", raw):
        w = m.group(0).lower().strip("'")
        if w and w.isascii() and w.isalpha() and len(w) >= 2:
            words.add(w)
    return words


def main() -> None:
    counts: dict[str, int] = {}
    for src in SOURCES:
        for w in extract(ROOT / src):
            counts[w] = counts.get(w, 0) + 1

    curated = {w.lower() for w in CURATED.split()
               if len(w) >= 2 and w.replace("'", "").isalpha()}

    # Corpus words appear at least twice across the sources (once in docs,
    # once in the i18n master, or across several docs) — a single stray
    # occurrence is probably a typo or a one-off name.
    kept = {w for w, c in counts.items() if c >= 2} | curated
    # apostrophes are allowed (contractions: don't, you're); everything else
    # must be plain letters
    kept = {w for w in kept
            if len(w) >= 2 and w.isascii() and w.replace("'", "").isalpha()}
    ordered = sorted(kept)

    body = " ".join(ordered)
    out = (
        '"""Embedded English dictionary for core/typecheck.py — GENERATED.\n'
        "Do not edit by hand; regenerate with:\n"
        "    uv run python tools/gen_typecheck_words.py\n"
        f'"""\n\nfrom __future__ import annotations\n\nBASE_WORDS: frozenset[str] = frozenset(\n    """{body}""".split()\n)\n'
    )
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT} with {len(ordered)} words ({len(body) // 1024} KB)")


if __name__ == "__main__":
    main()
