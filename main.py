import streamlit as st
import pandas as pd
import geopandas as gpd
import folium as fl
from streamlit_folium import st_fl

st.set_page_config (page_title= "Brisbane Political Map", layout= "wide")
st.title ("UUUuuuuU esque a mi me gusta tu actitud tiene sabor a bubaluu")

# LOCAL MAP BOUNDARIES
@st.cache_data
def load_local_map (filepath = "data/brisbane.geojson"):
    gdf             = gdp.read_file (filepath)
    gdf.columns     = gdf.columns.str.strip().str.lower()
    ward_col   = 'ward_name' if 'ward_name' in gdf.columns else 'name'
    return gdf, ward_col

# LOCAL CANDIDATE DATABASE
def load_local_database(filepath = "data/disclosures.csv"):
    df         = pd.read_csv(filepath)
    df.columns = df.columns.str.strip().str.lower()
    return df

try:
    # Load local assets
    gdf_wards, geo_ward_col = load_local_map()
    df_disclosures          = load_local_database()
    # Merge map with candidate database...
    gdf_merged = gdf_wards.merge(
        df_disclosures,
        left_on     = geo_ward_col,
        right_on    = "ward",
        how         = "left"
    )

    # Missing data placeholder.
    gdf_merged["total_donations_aud"] = gdf_merged["total_donations_aud"].fillna(0)
    gdf_merged["councillor"] = gdf_merged["councillor"].fillna("N/A")

    # The foluim map
    m = fl.Map(location=[-27.4705, 153.0260], zoom_start=11, tiles="CartoDB positron")

    fl.Choropleth(
        geo_data    = gdf_merged,
        name        = "Total Donations ($AUD)",
        data        = gdf_merged,
        columns     = [geo_ward_col, "total_donations_aud"],
        key_on      = f"feature.properties.{geo_ward_col}",
        fill_color  = "YlGnBu",
        fill_opacity= 0.6,
        line_opacity= 0.8,
        legend_name = "Total Political Donations Received ($AUD)"
    ).add_to(m)

    # Interacrive tooltips
    tooltip = fl.GeoJsonTooltip(
        fields      = [geo_ward_col, "councillor", "party", "total_donations_aud", "top_donor"],
        aliases     = ["Ward:", "Councillor:", "Party:", "Total Donations ($):", "Top Donor:"],
        localize    = True
    )
    fl.GeoJson(
        gdf_merged,
        style_function=lambda x: {'fillColor': '#ffffff00', 'color': '#000000', 'weight': 1},
        tooltip     =tooltip
    ).add_to(m)

    # Sidebar data view
    st_fl.sidebar.header ("Details")
    selected_ward = st.sidebar.selectbox ("Select Ward", sorted(gdf_merged [geo_ward_col].unique()))
    ward_info = df_disclosures[df_disclosures["ward"] == selected_ward]
    st.sidebar.dataframe(ward_info)

except Exception as e:
    st.error(f"[ERROR] {e}")   