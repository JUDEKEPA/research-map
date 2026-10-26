"""Empty optional catalogue; research is discovered from the chosen project."""
from pathlib import Path
SOURCE = Path(__file__).resolve().parent / 'demo' / 'Orchard Study'
BASE = ''
def build_catalog(root=SOURCE):
    return {'nodes': [], 'edges': [], 'source': str(root), 'source_available': Path(root).is_dir()}
