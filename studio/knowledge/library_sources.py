"""Explicit redistribution grants. Technical availability alone is not an import grant."""
SOURCES={
 'lichess-broadcasts':{
  'id':'lichess-broadcasts','name':'Lichess official broadcasts','page':'https://database.lichess.org/#broadcasts',
  'license':'CC-BY-SA-4.0','license_url':'https://creativecommons.org/licenses/by-sa/4.0/',
  'attribution':'Lichess official broadcasts and the tournaments linked in each record.',
  'evidence':'https://database.lichess.org/#broadcasts','category':'broadcast'},
 'figshare-4276523-v1':{
  'id':'figshare-4276523-v1','name':'Chess Database — Ana Schaigorodsky (2016)',
  'page':'https://doi.org/10.6084/m9.figshare.4276523.v1',
  'license':'CC-BY-4.0','license_url':'https://creativecommons.org/licenses/by/4.0/',
  'attribution':'Ana Schaigorodsky (2016), Chess Database, figshare. DOI: 10.6084/m9.figshare.4276523.v1. Related study: Schaigorodsky, Perotti and Billoni, PLOS ONE 11(12):e0168213.',
  'evidence':'https://api.figshare.com/v2/articles/4276523/versions/1','category':'historical'},
}

def get(source_id):
 if source_id not in SOURCES:raise ValueError('Source has no approved redistribution policy')
 return dict(SOURCES[source_id])
