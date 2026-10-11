"""Logical selections over DKT/aseg labels, not new meshes or functional atlases.

Lobes follow Klein & Tourville (2012), Table 2, restricted to the 31 DKT
labels actually present. Functional selections are deliberately coarse and
must retain their approximation notes in the UI and assistant context.
"""
from functools import lru_cache

DKT = 'https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2012.00171/full'
MULTIMODAL = 'https://www.nature.com/articles/nature18933'
PREFRONTAL = 'https://pubmed.ncbi.nlm.nih.gov/10103094/'
BROCA = 'https://pubmed.ncbi.nlm.nih.gov/10441759/'
LANGUAGE = 'https://pubmed.ncbi.nlm.nih.gov/15037129/'
MOVEMENT = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC10172144/'
NETWORKS = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3174820/'

FRONTAL = ('superiorfrontal', 'rostralmiddlefrontal', 'caudalmiddlefrontal',
           'parsopercularis', 'parstriangularis', 'parsorbitalis',
           'lateralorbitofrontal', 'medialorbitofrontal', 'precentral', 'paracentral')
PARIETAL = ('superiorparietal', 'inferiorparietal', 'supramarginal', 'postcentral', 'precuneus')
TEMPORAL = ('superiortemporal', 'middletemporal', 'inferiortemporal', 'fusiform',
            'transversetemporal', 'entorhinal', 'parahippocampal')
OCCIPITAL = ('lateraloccipital', 'lingual', 'cuneus', 'pericalcarine')
CINGULATE = ('rostralanteriorcingulate', 'caudalanteriorcingulate', 'posteriorcingulate', 'isthmuscingulate')
MOTOR = ('precentral', 'paracentral', 'caudalmiddlefrontal', 'superiorfrontal')
PFC = ('superiorfrontal', 'rostralmiddlefrontal', 'caudalmiddlefrontal', 'parsopercularis',
       'parstriangularis', 'parsorbitalis', 'lateralorbitofrontal', 'medialorbitofrontal')


def _definition(key, name, cortex=(), *, structures=(), kind='functional', note='',
                aliases=(), sources=(DKT, MULTIMODAL), default='bilateral'):
    return dict(key=key, name=name, cortex=cortex, structures=structures, kind=kind,
                description=note, aliases=aliases, sources=sources, default=default)


DEFINITIONS = (
    _definition('frontal', 'Frontallappen', FRONTAL, kind='lobe', aliases=('frontal lobe', 'Stirnlappen'), sources=(DKT,),
                note='DKT-Lappenkonvention: der ganze Lobulus paracentralis gehört hier zur frontalen Gruppe; er enthält auch somatosensorische Anteile.'),
    _definition('parietal', 'Parietallappen', PARIETAL, kind='lobe', aliases=('parietal lobe', 'Scheitellappen'), sources=(DKT,)),
    _definition('temporal', 'Temporallappen', TEMPORAL, kind='lobe', aliases=('temporal lobe', 'Schläfenlappen'), sources=(DKT,),
                note='Der gesamte DKT-Fusiform-Gyrus ist konventionsgemäß temporal zugeordnet; er reicht anatomisch auch nach okzipital.'),
    _definition('occipital', 'Okzipitallappen', OCCIPITAL, kind='lobe', aliases=('occipital lobe', 'Hinterhauptslappen'), sources=(DKT,)),
    _definition('m1', 'Primärer motorischer Kortex (M1)', ('precentral',), aliases=('M1', 'primärer motorischer Kortex', 'primary motor cortex'),
                note='DKT-basierte Annäherung über den ganzen Gyrus praecentralis; keine exakte Area-4-Grenze und keine vollständige mediale Beinrepräsentation.'),
    _definition('motor', 'Erweiterter motorischer Kortex', MOTOR, aliases=('motorischer Kortex', 'motorische Rinde', 'Motorkortex', 'motor cortex', 'Bewegungskortex', 'Bewegungsrinde'),
                sources=(DKT, MULTIMODAL, MOVEMENT),
                note='DKT-basierte Annäherung an M1, prämotorische und supplementär-motorische Gebiete. Ganze frontale/parazentrale Labels enthalten auch nichtmotorischen Kortex; SMA nicht separat segmentiert.'),
    _definition('pfc', 'Präfrontaler Kortex (PFC)', PFC, aliases=('PFC', 'präfrontaler Kortex', 'präfrontale Rinde', 'prefrontal cortex'), sources=(DKT, PREFRONTAL),
                note='Breite DKT-basierte Annäherung. Superiorfrontal und caudalmiddlefrontal enthalten auch prämotorische Anteile; keine cytoarchitektonische PFC-Grenze.'),
    _definition('dlpfc', 'Dorsolateraler präfrontaler Kortex (DLPFC)', ('rostralmiddlefrontal', 'caudalmiddlefrontal', 'superiorfrontal'),
                aliases=('DLPFC', 'dorsolateraler präfrontaler Kortex', 'dorsolateral prefrontal cortex'), sources=(DKT, PREFRONTAL),
                note='DKT-basierte Annäherung aus mittleren und oberen frontalen Gyri; überschätzt insbesondere medialen/prämotorischen Kortex und entspricht nicht exakt Area 9/46.'),
    _definition('ofc', 'Orbitofrontaler Kortex (OFC)', ('lateralorbitofrontal', 'medialorbitofrontal'),
                aliases=('OFC', 'orbitofrontaler Kortex', 'orbitofrontal cortex'), sources=(DKT, PREFRONTAL),
                note='DKT-basierte makroanatomische Annäherung, keine funktionelle Unterteilung des orbitofrontalen Kortex.'),
    _definition('s1', 'Primärer somatosensorischer Kortex (S1)', ('postcentral',),
                aliases=('S1', 'primärer somatosensorischer Kortex', 'somatosensorischer Kortex', 'somatosensorische Rinde', 'primary somatosensory cortex'),
                note='DKT-basierte Annäherung über den Gyrus postcentralis; keine exakte Abgrenzung der Areale 3a/3b/1/2 und der medialen Beinrepräsentation.'),
    _definition('v1', 'Primärer visueller Kortex (V1)', ('pericalcarine',), aliases=('V1', 'primärer visueller Kortex', 'primary visual cortex'),
                note='DKT-basierte Annäherung über pericalcarinen Kortex; keine individuell retinotopisch oder histologisch bestimmte V1-Grenze.'),
    _definition('visual_association', 'Visueller Assoziationskortex', ('lateraloccipital', 'cuneus', 'lingual'),
                aliases=('visueller Assoziationskortex', 'visual association cortex'),
                note='DKT-basierte Auswahl okzipitaler Assoziationsgebiete. Labels enthalten möglicherweise V1-Anteile; temporale/parietale Sehnetzwerke sind nicht vollständig abgebildet.'),
    _definition('visual', 'Visuelle Kortexregionen', OCCIPITAL + ('fusiform',), aliases=('visueller Kortex', 'Sehkortex', 'Sehrinde', 'visuelle Kortexregionen', 'visual cortex'),
                note='Breite DKT-basierte Annäherung an frühe und ventrale visuelle Verarbeitung; weder vollständig noch ein individuell gemessenes Sehnetzwerk.'),
    _definition('auditory', 'Primärer auditorischer Kortex (A1)', ('transversetemporal',),
                aliases=('A1', 'primärer auditorischer Kortex', 'auditorischer Kortex', 'Hörkortex', 'Hörrinde', 'primary auditory cortex'),
                note='DKT-basierte Annäherung über transversalen temporalen Kortex (Heschl); die funktionelle Hörkernregion entspricht nicht dem ganzen Gyrus.'),
    _definition('broca', 'Broca-Region', ('parsopercularis', 'parstriangularis'), aliases=('Broca', 'Broca-Areal', 'Broca-Region'),
                sources=(DKT, BROCA), default='left',
                note='DKT-basierte Annäherung an die linksseitige Broca-Region. Pars opercularis/triangularis sind nicht identisch mit Area 44/45. Rechts wird das homologe Gebiet gewählt, keine Sprachdominanz behauptet.'),
    _definition('wernicke', 'Wernicke-Region (grobe Annäherung)', ('superiortemporal', 'middletemporal', 'supramarginal', 'inferiorparietal'),
                aliases=('Wernicke', 'Wernicke-Areal', 'Wernicke-Region'), sources=(DKT, LANGUAGE), default='left',
                note='Sehr grobe DKT-basierte Annäherung: posteriore temporale und inferior-parietale Anteile sind nicht separat segmentiert, daher werden ganze Gyri gewählt. Kein exakt definiertes oder alleiniges Sprachverständniszentrum; rechts nur homologe Gebiete.'),
    _definition('cingulate', 'Cingulärer Kortex', CINGULATE, kind='anatomical', aliases=('cingulärer Kortex', 'cingulate cortex', 'Gyrus cinguli'), sources=(DKT,),
                note='Die vier DKT-Cingulumlabels bleiben als eigene anatomische Gruppe außerhalb der vier Lappen verfügbar.'),
    _definition('insula', 'Insulärer Kortex', ('insula',), kind='anatomical', aliases=('Inselrinde', 'insular cortex'), sources=(DKT,),
                note='Die Insula wird keinem der vier klassischen Großhirnlappen zugeschlagen.'),
    _definition('entorhinal', 'Entorhinaler Kortex', ('entorhinal',), kind='anatomical', aliases=('entorhinaler Kortex', 'entorhinal cortex'), sources=(DKT,)),
    _definition('parahippocampal', 'Parahippocampaler Kortex', ('parahippocampal',), kind='anatomical', aliases=('parahippocampaler Kortex', 'parahippocampal cortex'), sources=(DKT,)),
    _definition('limbic', 'Limbisches System (Auswahl)', CINGULATE + ('entorhinal', 'parahippocampal'),
                structures=('aseg.hippocampus', 'aseg.amygdala', 'aseg.accumbens', 'hypothalamus.hypothalamus'), kind='network',
                aliases=('limbisches System', 'limbic system'), sources=(DKT, NETWORKS),
                note='Didaktische anatomische Auswahl, kein einheitlich abgegrenztes oder individuell gemessenes Netzwerk und nicht das Yeo-Limbic-Netzwerk. Hypothalamus nur als Ganzes; Mammillarkörper, Fornix und Thalamuskerne nicht separat verfügbar.'),
    _definition('movement', 'Bewegungssteuerung (Auswahl)', MOTOR + ('postcentral', 'superiorparietal', 'caudalanteriorcingulate'),
                structures=('aseg.caudate', 'aseg.putamen', 'aseg.pallidum', 'aseg.thalamus', 'aseg.cerebellar_cortex',
                            'brainstem.midbrain', 'brainstem.pons', 'brainstem.medulla', 'brainstem.superior_cerebellar_peduncle'),
                kind='network', aliases=('Bewegungssteuerung', 'motorisches System', 'motor system'), sources=(DKT, MOVEMENT),
                note='Grobe anatomische Auswahl motorischer Regelkreise, kein gemessenes Netzwerk. Ganze Kerne/Hirnstammteile enthalten weitere Funktionen; Substantia nigra und Nucleus subthalamicus fehlen als separate Labels.'),
    _definition('hippocampus_amygdala', 'Hippocampus und Amygdala', structures=('aseg.hippocampus', 'aseg.amygdala'),
                kind='anatomical', aliases=('Hippocampus und Amygdala',), sources=(DKT,)),
    _definition('brainstem', 'Hirnstamm', structures=('brainstem.midbrain', 'brainstem.pons', 'brainstem.medulla'),
                kind='anatomical', aliases=('Hirnstamm', 'Gehirnstamm', 'brainstem', 'brain stem'),
                sources=('https://www.ncbi.nlm.nih.gov/books/NBK544297/',),
                note='Mittelhirn, Pons und Medulla oblongata. Der separat segmentierte obere Kleinhirnstiel gehört nicht zu dieser Auswahl.'),
    _definition('cerebellum', 'Kleinhirn', structures=('aseg.cerebellar_cortex', 'aseg.cerebellar_white_matter'),
                kind='anatomical', aliases=('Kleinhirn', 'cerebellum'), sources=()),
    _definition('cortex', 'Großhirnrinde', FRONTAL + PARIETAL + TEMPORAL + OCCIPITAL + CINGULATE + ('insula',),
                kind='anatomical', aliases=('Großhirnrinde', 'cerebral cortex'), sources=(DKT,)),
)


def _members(definition, ids, hemisphere):
    hemis = ('lh', 'rh') if hemisphere == 'bilateral' else ('lh',) if hemisphere == 'left' else ('rh',)
    wanted = {f'cortex.dkt.{hemi}.{region}' for hemi in hemis for region in definition['cortex']}
    for structure in definition['structures']:
        source, region = structure.split('.', 1)
        for hemi in hemis:
            wanted.add(f'subcortex.{source}.{hemi}_{region}')
        # Unsplit midline labels cannot truthfully be selected as left or right.
        if hemisphere == 'bilateral':
            wanted.add(f'subcortex.{source}.{region}')
    return [region_id for region_id in ids if region_id in wanted]


@lru_cache(maxsize=8)
def _cached_groups(ids):
    result = []
    for definition in DEFINITIONS:
        for suffix, hemisphere in [('', definition['default']), ('.left', 'left'), ('.right', 'right'), ('.bilateral', 'bilateral')]:
            members = _members(definition, ids, hemisphere)
            if not members:
                continue
            side_name = {'left': 'links', 'right': 'rechts', 'bilateral': 'beidseitig'}[hemisphere]
            base_aliases = list(dict.fromkeys((definition['name'],) + definition['aliases']))
            aliases = base_aliases if not suffix else [f'{alias} {side_name}' for alias in base_aliases]
            name = definition['name'] + (f' {side_name}' if suffix else '')
            result.append(dict(group_id='group.' + definition['key'] + suffix, name=name,
                hemisphere=hemisphere, region_ids=members, approximation=definition['kind'] in ('functional', 'network'),
                kind=definition['kind'], description=definition['description'], aliases=aliases,
                sources=list(definition['sources'])))
    return tuple(result)


def groups_for_ids(ids):
    return [dict(group, region_ids=list(group['region_ids']), aliases=list(group['aliases']), sources=list(group['sources']))
            for group in _cached_groups(tuple(ids))]


def assistant_group_context(ids):
    """One definition per family; explicit side IDs remain in the tool enum."""
    groups = groups_for_ids(ids)
    by_id = {group['group_id']: group for group in groups}
    result = []
    for group in groups:
        if group['group_id'].count('.') != 1:
            continue
        item = {key: group[key] for key in ('group_id', 'name', 'hemisphere', 'approximation', 'description', 'aliases')}
        item['sides'] = {side: group['group_id'] + '.' + side for side in ('left', 'right', 'bilateral')
                         if group['group_id'] + '.' + side in by_id}
        result.append(item)
    return result
