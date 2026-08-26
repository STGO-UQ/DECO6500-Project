import urllib.request
import os

# official QSpatial open data geojson 4 Brizzy wards (26 total)
url = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Boundaries/AdministrativeBoundaries/MapServer/8/query?where=1%3D1&outFields=*&f=geojson"
output_path = os.path.join("..", "data", "brisbane.geojson")
os.makedirs(os.path.dirname(output_path), exist_ok=True)
print (f"Downloading to {output_path}")

try:
    urllib.request.urlretrieve(url, output_path)
    print ("[Done]")
except Exception as e:
    print (f"[Failure] : {e}")