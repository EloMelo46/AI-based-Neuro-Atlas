# Anatomische und funktionelle Regionsgruppen

Die Definitionen in `main/region_groups.py` bestehen ausschließlich aus IDs des
aktuellen `regions_manifest.tsv`. Sie erzeugen keine neue Geometrie. Das Manifest
enthält 31 DKT-Labels pro Hemisphäre; Frontalpol, Temporalpol und Banks-of-STS
sind darin nicht eigenständig vorhanden und werden nicht hinzuerfunden.

## Anatomische Lappen

Die vier Lappen folgen der DKT-Konvention aus Tabelle 2 und dem Anhang von
[Klein & Tourville (2012)](https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2012.00171/full).
Pro Seite umfassen sie 10 frontale, 5 parietale, 7 temporale und 4 okzipitale
Labels. Die vier cingulären Labels und die Insula bleiben eigene Gruppen.
Die [FreeSurfer-Dokumentation](https://surfer.nmr.mgh.harvard.edu/fswiki/CorticalParcellation#Lobe_mapping)
erläutert, dass eine solche Ganzlabel-Zuordnung Grenzfälle hat: Fusiformis
reicht über die temporo-okzipitale Grenze; Paracentralis enthält motorische
und somatosensorische Anteile. Die Anwendung ordnet diese ungeteilten Labels
entsprechend der dokumentierten Lappenkonvention zu und schneidet keine
anatomisch erfundenen Teilmeshes daraus.

## Funktionelle Auswahlen und ihre Grenzen

Alle nachfolgend als funktionell bezeichneten Gruppen tragen
`approximation=true`, einen individuellen Hinweis und Quellenlinks. Der
Assistent erhält diese Hinweise; bei Werkzeugaufrufen bleiben sie ausserdem
als `selection_groups` erhalten, nachdem die IDs für den Viewer expandiert
wurden. Normale Auswahlmeldungen hängen diese Hinweise nicht automatisch an.
Der Assistent erläutert sie auf Nachfrage zur Genauigkeit oder wenn eine
konkrete Einschränkung für die Antwort relevant ist. Eine funktionelle Lokalisation wurde an diesem individuellen MRT
nicht gemessen. Dass gyrale Labels funktionelle Grenzen nicht ersetzen, wird
unter anderem durch die multimodale Parzellierung von
[Glasser et al. (2016)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4990127/)
belegt. Die konkrete Zuordnung ganzer DKT-Labels ist eine didaktische
Implementierungsentscheidung, kein dort veröffentlichter DKT-Funktionsatlas.

| Auswahl | Vorhandene DKT-Grundlage | Sichtbare Einschränkung |
| --- | --- | --- |
| M1 | Precentralis | Ganzes Label, keine exakte Area 4; mediale Beinrepräsentation nicht vollständig |
| Erweiterter motorischer Kortex | Precentralis, Paracentralis, Caudalmiddlefrontal, Superiorfrontal | Grobe M1-/Prämotor-/SMA-Näherung; nichtmotorische Anteile eingeschlossen |
| PFC | Obere/mittlere frontale Gyri, die drei Pars-Labels, mediales/laterales OFC | Auch prämotorische Anteile enthalten |
| DLPFC | Rostral-/Caudalmiddlefrontal, Superiorfrontal | Ganze Gyri; mediale und prämotorische Anteile nicht trennbar |
| OFC | Laterales und mediales Orbitofrontal-Label | Makroanatomisch, keine funktionellen Unterfelder |
| S1 | Postcentralis | Keine exakten Areale 3a/3b/1/2; mediale Beinrepräsentation nicht vollständig |
| V1 | Pericalcarine | Keine individuelle Retinotopie oder histologische Grenze |
| Visuelle Assoziation | Lateraloccipital, Cuneus, Lingual | Labels können V1-Anteile enthalten; nicht das gesamte Sehnetzwerk |
| Visuelle Kortexregionen | Okzipitale Labels plus Fusiformis | Breite, unvollständige Auswahl |
| A1 | Transversetemporal | Heschl-Label entspricht nicht exakt dem Hörkern |
| Broca | Pars opercularis und triangularis, standardmäßig links | Keine exakte Area 44/45; Sprachdominanz nicht gemessen |
| Wernicke | Superior-/Middletemporal, Supramarginal, Inferiorparietal, standardmäßig links | Besonders grob: posteriore Unterteilungen fehlen, daher ganze Gyri |

Die PFC-/DLPFC-Näherung orientiert sich an der cytoarchitektonischen Arbeit von
[Petrides & Pandya (1999)](https://pubmed.ncbi.nlm.nih.gov/10103094/).
Sie begründet keine Gleichsetzung eines kompletten DKT-Gyrus mit Area 9/46.
[Amunts et al. (1999)](https://pubmed.ncbi.nlm.nih.gov/10441759/)
untersuchten die individuelle Variabilität der Broca-Region; deshalb sind
Pars-Labels hier nur Näherungen. Für Wernicke wird die verteilte Beteiligung
an Sprachverstehen aus [Dronkers et al. (2004)](https://pubmed.ncbi.nlm.nih.gov/15037129/)
berücksichtigt. Der Gruppenname bezeichnet kein einziges, exakt umgrenztes
Sprachverständniszentrum. Rechte Sprachgruppen sind homologe anatomische
Auswahlen und keine Behauptung rechtshemisphärischer Sprachdominanz.

Cingulärer, entorhinaler und parahippocampaler Kortex sind direkt aufrufbare
anatomische DKT-Gruppen. Ihr `approximation=false` bedeutet nur, dass keine
zusätzliche funktionelle Zuordnung vorgenommen wird; es ist keine Aussage
über die Genauigkeit der individuellen Segmentierung.

## Systeme

**Limbisches System:** eine explizite didaktische Auswahl aus Cingulum,
entorhinalem/parahippocampalem Kortex, Hippocampus, Amygdala, Accumbens und
Hypothalamus. Die Auswahl ist weder eine erschöpfende Definition des
limbischen Systems noch das funktionelle Yeo-Limbic-Netzwerk. Fornix,
Mammillarkörper und einzelne Thalamuskerne fehlen als separat auswählbare
Labels. [Yeo et al. (2011)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3174820/)
ist als methodischer Hinweis auf funktionell ermittelte Netzwerke verlinkt,
nicht als Beleg für eine Gleichsetzung mit dieser selbst definierten Gruppe.

**Bewegungssteuerung:** erweitert die motorische Kortexauswahl um
Postcentralis, Superiorparietal, kaudales anteriores Cingulum, Caudatus,
Putamen, Pallidum, Thalamus, Kleinhirnrinde und vorhandene Hirnstammteile.
[Gordon et al. (2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10172144/)
zeigt die verteilte Organisation motorischer Regelkreise und die Grenzen
einer Gleichsetzung mit dem gesamten präzentralen Gyrus. Unsere Gruppe ist
keine Reproduktion des SCAN-Netzwerks. Ganze Kerne, Kleinhirnrinde und
Hirnstammteile schließen nichtmotorische Funktionen ein. Substantia nigra
und Nucleus subthalamicus fehlen als einzelne Labels.

## Seiten und alte IDs

`group.frontal`, beispielsweise, wählt beidseitig; `.left`, `.right` und
`.bilateral` sind explizite Varianten. Broca und Wernicke wählen ohne
Seitenangabe links. Ungeteilte Mittellinienstrukturen werden in einseitigen
Gruppen nicht als vermeintlich einseitige Geometrie mitselektiert.

Alte Struktur-IDs wie `Left-Thalamus` und `Right-Hippocampus` werden auf die
neuen Manifest-IDs abgebildet. Alte Großhirnrinden-IDs expandieren in die 31
DKT-Labels der jeweiligen Seite; `Brain-Stem` und `group.brainstem` expandieren
in Mittelhirn, Pons und Medulla oblongata. Der separat segmentierte obere
Kleinhirnstiel bleibt einzeln aufrufbar und ist nicht Mitglied dieser Auswahl.
Die drei Hirnstammabschnitte sind auch im [NCBI-Überblick](https://www.ncbi.nlm.nih.gov/books/NBK544297/) so beschrieben;
die Kleinhirnstiele verbinden Kleinhirn und Hirnstamm. Die alten `CC_*`-Teilregionen und
`*-Inf-Lat-Vent` lassen sich nur auf das nun zusammengefasste Corpus-callosum-
beziehungsweise Seitenventrikel-Label abbilden. Ein solcher Aufruf erhält
einen ausdrücklichen `selection_notes`-Hinweis. Das behauptet keine
weiterbestehende separate Segmentierung des ehemaligen Teilareals.
Die zusätzlichen VentralDC-Reste, WM-hypointensities und der nicht zugeordnete
Hirnstamm-Rest sind technische Füllgeometrien. Sie sind weder auswählbar noch
Mitglieder anatomischer Gruppen und werden nicht als neue funktionelle Areale
ausgegeben. Der störende Hirnstamm-Rest ist zusätzlich im Manifest vollständig
deaktiviert und wird weder als Oberfläche noch als Schnittfläche geladen.
Die anderen drei Füllgeometrien bleiben aktiv.
CSF/Liquor ist separat über `csf.aseg.missing_csf_24` auswählbar:
normalerweise verborgen, bei Schnitten durch das vollständig eingeblendete
Gehirn automatisch als Füllfläche sichtbar (nicht bei Einzel-/Gruppenfokus),
und nur auf ausdrückliche Bitte hervorgehoben. Es bezeichnet den zusätzlichen
Anteil von FreeSurfer-Label 24, nicht den gesamten Liquorraum.

Die Auswahlvalidierung vereinigt überlappende Gruppen und Einzelregionen
vor der Ausführung. Sichtbarkeit, Deckkraft, Hervorhebung und Schnitt bleiben
Eigenschaften genau eines geladenen Objekts pro `region_id`.

## Gemeinsamer Wortschatz

`main/region_vocabulary.py` ergänzt deutsche, lateinische und englische Namen
für alle 55 Labeltypen. Der Katalog wird für KI-Kontext (Text und Realtime),
Auswahlvalidierung und den Leuchteffekt während Erklärungen gemeinsam verwendet.
Paarige Einzelregionen werden ohne Seitenangabe beidseitig aufgelöst; links/rechts,
Umlaut-Umschreibungen und die gebräuchlichen deutschen Adjektivbeugungen bleiben
berücksichtigt. Beispiele: verlängertes Mark/Nachhirn → Medulla oblongata,
Brücke → Pons, Hirnanhangsdrüse → Hypophyse, Zirbeldrüse → Epiphyse,
Mandelkern → Amygdala, Vormauer → Claustrum, vordere Zentralwindung → Gyrus praecentralis.

Auf ausdrücklichen Nutzerwunsch wählt eine **Zeigebitte** nach Rückenmark,
Medulla spinalis oder spinal cord die vorhandene Medulla oblongata. Das ist
eine dokumentierte Auswahlkonvention, kein anatomisches Synonym: das eigentliche
Rückenmark ist nicht segmentiert. KI-Kontext und Werkzeughinweis benennen diesen
Unterschied. Bei reinen Erklärungen löst Rückenmark keinen falschen Medulla-
Leuchteffekt aus. Mittlere und untere Kleinhirnstiele werden ebenfalls nicht
auf den vorhandenen oberen Stiel umgedeutet.

Funktionelle Bezeichnungen wie Bewegungsrinde, Sehrinde oder Hörrinde verwenden
weiterhin die vorhandenen Gruppen mit ihren DKT-Annäherungshinweisen. Aus
Funktionsbeschreibungen wie „Gedächtniszentrum“ wird keine exakte Einzelregion erfunden.
