# FastPrompter mannekeenidele (vanaisa seletab)

> Istu maha, võta tee. Asja lühidalt, ilma tuulutamiseta.

## Mis see on

Ühe-kiirklahvi märkmik. Vajutad `Alt+X` — aken hüppab kursori juurde.
Vajutad `Esc` — kadunud. Nagu kägukell, aga kasulik. Sees: sada
nummerdatud visandilahtrit ("silod") tekstile, valmissnipid
`F1`–`F10`, projektikaardid, igale märkmele oma failisahtel, arhiiv,
prügikast. See on kaasaskantav Windowsi rakendus — ei installi, ei
adminiõigusi.

## Milleks see on

Et sa ei kaotaks mõtet, samal ajal kui märkmikku otsid. AI-le mõeldud
prompt, kooditükk, ostunimekiri, mustandkiri — kirjutad, aken peidab
iseenda, tekst on juba salvestatud. "Salvesta" nuppu pole vaja vajutada:
hetkel, kui kirjutamise lõpetad, on see juba kettal. Elekter sureb
lause keskel — lahtrid jäävad ellu.

## Miks mitte lihtsalt pilv

Sest su visandtekst pole kellegi teise asi. Kõik elab ühes `data/`
kaustas programmi kõrval: ei kontot, ei pilve, ei telemeetriat.
Kopeerid selle kausta USB-pulga peale — see ongi su varukoopia ja terve
install ühe liigutusega.

## Kus mis asub

- `data/local_data_v15.db` — andmebaas, kirjutatakse reaalajas.
- `data/files/<projekt>/<silo>/` — iga märkme manused, tavalised kaustad,
  ava Exploreris millal tahad.
- `data/files/_trash/` — kuhu keskmise klõpsuga silo läheb: siin ei põle
  miski, saad alati tagasi õngitseda.
- `Documents\.fastprompter\` — igapäevane lihtsa markdowni peegel
  kõigest, juhuks kui rakendus ise kunagi ei käivitu — tekst loetakse
  ikka igas redaktoris.

## Kuidas seda tegelikult kasutada (lühike versioon)

- `Alt+X` — kutsu/peida aken kust iganes.
- `F1`–`F10` / `Ctrl+Shift+1`–`9` — kleebi snippet 1-10.
- `Ctrl+1`–`Ctrl+0` — hüppa silole 1-10.
- `Ctrl+N` — värske tühi silo; `Alt+Up`/`Alt+Down` — liigu nende vahel.
- `Ctrl+W` — sisesta vahedega --- eraldaja.
- `Alt+W` — sisesta vahedega --- eraldaja ja alusta uut märki.
- `Ctrl+E` — muuda rida päiseks: # + paks + allajoonitud + ajatempel.
- `Ctrl+Return` — lülita [ ] märkeruute.
- `Ctrl+B` / `Ctrl+I` / `Ctrl+U` / `Ctrl+T` — paks, kaldkiri, allajoonitud, läbitõmmatud.
- `Alt+Backspace` — kustuta eelmine sõna.
- `Ctrl+S` — salvesta snippet.
- `Ctrl+D` — zen-režiim.
- `Ctrl+Q` — klõpsa aken nurkadesse.
- Keskmine klõps silol — saadab prügikasti (mitte igaveseks).
- Hõljuta hiirt silo kohal — ilmuvad nupud: linnuke ✅, failid 📁, nööpnõel 📌, arhiiv 📥.
- Paremklõps projektiloendil — lisa, nimeta ümber või kustuta projektikaarte.

Täielik funktsioonide loend, ekraanipildid ja iga nupu lahtiseletus on
[README.md](README.md#инструкция--instruction) — terve vanaisa-hääles
peatükk nii inglise kui vene keeles.

## Lõppkokkuvõte

Üks kiirklahv — `Alt+X` — ja kogu su mõtete, koodi ja linkide segadus
elab ühes kohas, ei liigu kuhugi ja ei anna kellelegi aru. Vanaisa
kiidab heaks.
