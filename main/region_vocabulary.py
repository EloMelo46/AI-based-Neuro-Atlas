"""Shared German/Latin/English selection vocabulary for the actual atlas labels.

Names denote whole segmented labels. Functional approximations live in
region_groups; the explicitly requested spinal-cord shortcut has its own note.
"""
import re


REGION_SYNONYMS = {
    'missing_csf_24': ('CSF', 'Liquor', 'Liquor cerebrospinalis', 'Hirnflüssigkeit',
                       'Gehirnflüssigkeit', 'Nervenwasser', 'Cerebrospinal fluid'),
    'caudalanteriorcingulate': ('Kaudaler vorderer cingulärer Kortex', 'caudal anterior cingulate', 'Vorderer cingulärer Kortex', 'Anteriorer cingulärer Kortex'),
    'rostralanteriorcingulate': ('Rostraler vorderer cingulärer Kortex', 'rostral anterior cingulate', 'Vorderer cingulärer Kortex', 'Anteriorer cingulärer Kortex'),
    'posteriorcingulate': ('Hinterer cingulärer Kortex', 'posterior cingulate cortex'),
    'isthmuscingulate': ('Isthmus cinguli', 'Cingulumisthmus', 'isthmus cingulate', 'Isthmus des cingulären Kortexes'),
    'caudalmiddlefrontal': ('Kaudaler mittlerer Stirngyrus', 'Kaudaler mittlerer frontaler Gyrus', 'caudal middle frontal gyrus', 'Gyrus frontalis medius', 'Mittlere Stirnwindung',
                           'Mittlerer frontaler Gyrus, kaudal', 'Mittlerer frontaler Gyrus kaudal'),
    'rostralmiddlefrontal': ('Rostraler mittlerer Stirngyrus', 'Rostraler mittlerer frontaler Gyrus', 'rostral middle frontal gyrus', 'Gyrus frontalis medius', 'Mittlere Stirnwindung',
                            'Mittlerer frontaler Gyrus, rostral', 'Mittlerer frontaler Gyrus rostral'),
    'superiorfrontal': ('Gyrus frontalis superior', 'Obere Stirnwindung', 'Oberer Stirngyrus', 'superior frontal gyrus', 'Oberer frontaler Gyrus'),
    'cuneus': ('Keillappen',),
    'precuneus': ('Präcuneus', 'Präkuneus'),
    'entorhinal': ('Entorhinalrinde', 'entorhinal cortex', 'Cortex entorhinalis'),
    'fusiform': ('Spindelwindung', 'Spindelförmiger Gyrus', 'fusiform gyrus'),
    'inferiorparietal': ('Lobulus parietalis inferior', 'Unteres Scheitelläppchen', 'inferior parietal lobule', 'Unterer parietaler Lobulus'),
    'superiorparietal': ('Lobulus parietalis superior', 'Oberes Scheitelläppchen', 'superior parietal lobule', 'Oberer parietaler Lobulus'),
    'inferiortemporal': ('Gyrus temporalis inferior', 'Untere Schläfenwindung', 'Unterer temporaler Gyrus', 'inferior temporal gyrus'),
    'middletemporal': ('Gyrus temporalis medius', 'Mittlere Schläfenwindung', 'Mittlerer Schläfengyrus', 'middle temporal gyrus'),
    'superiortemporal': ('Gyrus temporalis superior', 'Obere Schläfenwindung', 'Oberer temporaler Gyrus', 'superior temporal gyrus'),
    'lateraloccipital': ('Laterale Okzipitalrinde', 'Laterale Hinterhauptsrinde', 'lateral occipital cortex'),
    'lateralorbitofrontal': ('Laterale Orbitofrontalrinde', 'lateral orbitofrontal cortex'),
    'medialorbitofrontal': ('Mediale Orbitofrontalrinde', 'medial orbitofrontal cortex'),
    'lingual': ('Zungenwindung', 'lingual gyrus'),
    'parahippocampal': ('Gyrus parahippocampalis', 'Parahippocampale Windung', 'parahippocampal cortex', 'parahippocampal gyrus'),
    'paracentral': ('Parazentralläppchen', 'Parazentraler Lobulus', 'paracentral lobule'),
    'parsopercularis': ('Operkulärer Teil des unteren Stirngyrus', 'pars opercularis of inferior frontal gyrus'),
    'parsorbitalis': ('Orbitaler Teil des unteren Stirngyrus', 'pars orbitalis of inferior frontal gyrus'),
    'parstriangularis': ('Triangulärer Teil des unteren Stirngyrus', 'pars triangularis of inferior frontal gyrus'),
    'pericalcarine': ('Pericalcarine Rinde', 'Perikalcariner Kortex', 'Perikalkariner Kortex', 'pericalcarine cortex'),
    'postcentral': ('Gyrus postzentralis', 'Postzentraler Gyrus', 'Hintere Zentralwindung', 'postcentral gyrus'),
    'precentral': ('Gyrus präcentralis', 'Gyrus präzentralis', 'Präzentraler Gyrus', 'Vordere Zentralwindung', 'precentral gyrus', 'Gyrus precentralis'),
    'supramarginal': ('Supramarginale Windung', 'supramarginal gyrus'),
    'transversetemporal': ('Heschl-Windung', 'Heschlsche Querwindung', 'Heschl-Gyrus', 'Gyri temporales transversi', 'transverse temporal cortex',
                          'Transversaler temporaler Kortex', 'transverse temporal gyrus'),
    'insula': ('Insel', 'Inselrinde', 'Insulärer Kortex', 'insular cortex'),
    'cerebral_white_matter': ('Großhirnmark', 'Weiße Substanz des Großhirns', 'cerebral white matter'),
    'cerebellar_white_matter': ('Kleinhirnmark', 'Weiße Substanz des Kleinhirns', 'cerebellar white matter'),
    'cerebellar_cortex': ('Kleinhirnkortex', 'Rinde des Kleinhirns', 'cerebellar cortex'),
    'thalamus': ('Thalami', 'Sehhügel'),
    'caudate': ('Caudatus', 'Schweifkern', 'Schweifkerne', 'Nuclei caudati', 'caudate nucleus'),
    'putamen': ('Schalenkern', 'Schalenkerne', 'Putamina'),
    'pallidum': ('Pallidum', 'Bleicher Kern', 'pallidum'),
    'hippocampus': ('Hippokampus', 'Hippocampi', 'Hippokampi'),
    'amygdala': ('Mandelkern', 'Mandelkerne', 'Amygdalen', 'Amygdalae', 'Corpus amygdaloideum'),
    'accumbens': ('Accumbens', 'Accumbenskern', 'Accumbens-Kern', 'nucleus accumbens'),
    'corpus_callosum': ('Hirnbalken', 'Gehirnbalken', 'Balken'),
    'lateral_ventricle': ('Seitenventrikel', 'ventriculus lateralis', 'ventriculi laterales', 'lateral ventricle'),
    'third_ventricle': ('Dritter Ventrikel', '3. Ventrikel', 'Ventrikel III', 'Ventrikel 3', 'ventriculus tertius', 'third ventricle'),
    'fourth_ventricle': ('Vierter Ventrikel', '4. Ventrikel', 'Ventrikel IV', 'Ventrikel 4', 'ventriculus quartus', 'fourth ventricle'),
    'midbrain': ('Mesencephalon', 'Mesenzephalon', 'midbrain', 'Mittelhirns'),
    'pons': ('Brücke', 'Hirnbrücke', 'Varolsche Brücke', 'Pons Varolii'),
    'medulla': ('Verlängertes Mark', 'Verlängertes Rückenmark', 'Nachhirn', 'Myelencephalon', 'Myelenzephalon', 'medulla'),
    'superior_cerebellar_peduncle': ('Kleinhirnstiel', 'Kleinhirnstiele', 'Obere Kleinhirnstiele', 'Pedunculus cerebellaris superior', 'Pedunculi cerebellares superiores', 'Brachium conjunctivum', 'superior cerebellar peduncle'),
    'hypothalamus': ('Hypothalamischer Bereich', 'hypothalamus'),
    'hypophyse': ('Hirnanhangsdrüse', 'Hypophysis', 'pituitary gland', 'pituitary'),
    'epiphyse': ('Zirbeldrüse', 'Pinealdrüse', 'Glandula pinealis', 'Corpus pineale', 'Epiphysis', 'pineal gland'),
    'infundibulum': ('Hypophysenstiel', 'Hypophysenstängel', 'pituitary stalk'),
    'claustrum': ('Vormauer', 'Vormauern'),
}

MEDULLA_ID = 'subcortex.brainstem.medulla'
SELECTION_SHORTCUTS = {'Rückenmark': MEDULLA_ID, 'spinal cord': MEDULLA_ID, 'Medulla spinalis': MEDULLA_ID}
UNAVAILABLE_NARRATION_NAMES = ('Medulla spinalis', 'Unterer Kleinhirnstiel', 'Mittlerer Kleinhirnstiel',
                             'Untere Kleinhirnstiele', 'Mittlere Kleinhirnstiele',
                             'Pedunculus cerebellaris inferior', 'Pedunculus cerebellaris medius',
                             'inferior cerebellar peduncle', 'middle cerebellar peduncle')
SPINAL_CORD_NOTE = ('Auswahlkonvention dieses Viewers: Bei einer Zeigebitte nach Rückenmark wird die Medulla oblongata '
                    '(verlängertes Mark) gezeigt. Das eigentliche Rückenmark ist nicht separat segmentiert und ist '
                    'anatomisch nicht mit der Medulla oblongata gleichzusetzen.')


def normalize_selection_name(value):
    value = value.casefold().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
    value = re.sub(r'[\s\-\u2010\u2011]+', ' ', value).strip()
    side = re.match(r'^(link(?:e[nmrs]?|s)|left|recht(?:e[nmrs]?|s)|right) (.+)$', value)
    if side:
        value = side[2] + (' links' if side[1].startswith(('link', 'left')) else ' rechts')
    # Explicitly accept the requested term under German case inflection.
    return re.sub(r'\bverlaengert(?:e[nmrs]?)\b', 'verlaengertes', value)


def names_for(bare, display_name):
    return list(dict.fromkeys((display_name, *REGION_SYNONYMS.get(bare, ()))))
