import streamlit as st
import geopandas as gpd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Brisbane Boundary Viewer", layout="wide")
st.title("gugugaga")

@st.cache_data
def load_geojson(filepath="data/brisbane.json"):
    gdf         = gpd.read_file(filepath)
    gdf.columns = gdf.columns.str.strip().str.lower()
    return gdf

try:
    # Load local
    gdf = load_geojson("data/brisbane.json")

    st.write(f"loaded {len(gdf)} features/polygons.")

    # Display column names
    with st.expander("View Data Table & Columns"):
        st.dataframe(gdf.drop(columns="geometry", errors="ignore"))

    # centroid bounds
    bounds     = gdf.total_bounds  # [minx, miny, maxx, maxy]
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2

    # Initialize centered folium map
    m         = folium.Map(location=[center_lat, center_lon], zoom_start=11, tiles="CartoDB positron")
    label_col = next((col for col in ['ward_name', 'name', 'ward', 'sec_name'] if col in gdf.columns), gdf.columns[0])

    # Polygon boundaries
    folium.GeoJson(
        gdf,
        style_function=lambda x: {
            'fillColor': '#3186cc',
            'color': '#000000',
            'weight': 1.5,
            'fillOpacity': 0.4,
        },
        highlight_function=lambda x: {
            'weight': 3,
            'fillOpacity': 0.7,
        },
        tooltip=folium.GeoJsonTooltip(fields=[label_col], aliases=["Boundary Name:"])
    ).add_to(m)

    # RENDER
    st_folium(m, width=1000, height=600)

except FileNotFoundError:
    st.error("Could not find `data/brisbane.json`. Please verify the path and filename.")
except Exception as e:
    st.error(f"Error loading map boundaries: {e}")