import streamlit as st
import requests
import random
import sys
import Levenshtein 
import pandas as pd
import time
import plotly.express as px
import plotly.graph_objects as go

# --- 0. STREAMLIT PAGE CONFIGURATION ---
st.set_page_config(layout="wide", page_title="TerraCaughta", page_icon="🌎")

# --- 1. CONFIGURATION ---
REST_COUNTRIES_API_BASE = "https://restcountries.com/v3.1"
WORLD_BANK_API_BASE = "http://api.worldbank.org/v2/country"
MAX_MISTAKES = 3

# POINT SYSTEM: Points awarded for solving the puzzle at each clue level (0-indexed)
POINT_MAP = {0: 10, 1: 8, 2: 6, 3: 4, 4: 2} 

# --- 2. HELPER FUNCTIONS ---

def normalize_text(text):
    """Removes casing and strips whitespace for a more forgiving comparison."""
    return str(text).lower().strip()

def get_border_names(border_codes):
    """Translates 3-letter country border codes into full names."""
    if border_codes == ['Island']:
        return "It is an island country or surrounded by a single nation."
    
    border_codes_str = ",".join(border_codes)
    url = f"{REST_COUNTRIES_API_BASE}/alpha?codes={border_codes_str}&fields=name,population"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        border_data = response.json()
        border_data_sorted = sorted(border_data, key=lambda x: x.get('population', 0), reverse=True)
        top_borders = [country['name']['common'] for country in border_data_sorted][:3]
        return ", ".join(top_borders)
    except Exception:
        return "Border data unavailable."

def get_world_bank_clue(country_iso_code):
    """
    Fetches coordinates and Income Level, and formats them for the desired structured output.
    Returns a dictionary containing formatted strings and raw lat/lon values.
    """
    url = f"{WORLD_BANK_API_BASE}/{country_iso_code}?format=json&per_page=1"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()[1][0]
        
        # Parse data
        lat = float(data['latitude'])
        lon = float(data['longitude'])
        income_level = data['incomeLevel']['value']
        
        if not lat or not lon:
             return {'location': 'Unavailable', 'classification': 'Unavailable', 'lat': None, 'lon': None}

        # Determine directions (N/S, E/W)
        lat_dir = 'N' if lat >= 0 else 'S'
        lon_dir = 'E' if lon >= 0 else 'W'
        
        abs_lat = round(abs(lat), 2)
        abs_lon = round(abs(lon), 2)
        
        # Create the two separate components for structured display
        location_string = f"**{abs_lat}°** {lat_dir}, **{abs_lon}°** {lon_dir}"
        classification_string = f"**{income_level}**"
        
        return {
            'location': location_string,
            'classification': classification_string,
            'lat': lat,
            'lon': lon
        }
    except Exception:
        return {'location': 'Unavailable', 'classification': 'Unavailable', 'lat': None, 'lon': None}

# --- PLOTLY IMPLEMENTATION FOR ZOOMABLE, UNLABELED MAP ---
def plot_coordinate_clue(lat, lon):
    """Plots the coordinate using Plotly for a zoomable, unlabeled map."""
    if lat is None or lon is None:
        st.warning("Map Clue: Cannot plot due to missing coordinates.")
        return
    
    # Create a DataFrame for Plotly
    map_data = pd.DataFrame({'lat': [lat], 'lon': [lon]})
    
    # 1. Create the base figure
    fig = go.Figure(data=go.Scattergeo(
        locationmode = 'ISO-3',
        lon = map_data['lon'],
        lat = map_data['lat'],
        mode = 'markers',
        marker = dict(
            size = 12,           # Marker size (small dot)
            color = 'red',       # Marker color
            line_width = 1,
            symbol='circle',
        )
    ))
    
    # 2. Configure the layout for an unlabeled, zoomable map
    fig.update_layout(
        geo = dict(
            scope='world',
            landcolor='rgb(30, 30, 30)',      # Dark land color
            coastlinecolor='rgb(100, 100, 100)', # Dark coastline
            showland = True,
            showcountries = True,
            showocean = True,
            oceancolor = 'rgb(17, 17, 17)',  # Dark ocean color
            projection_type = 'natural earth', 
            lataxis = dict(showgrid=True, gridcolor='gray', griddash='dot'),
            lonaxis = dict(showgrid=True, gridcolor='gray', griddash='dot'),
        ),
        margin={"r":0,"t":0,"l":0,"b":0},
        height=400,
        template='plotly_dark' 
    )
    
    # Set the initial view to zoom in slightly on the marker's location
    fig.update_geos(
        lataxis_range=[lat - 30, lat + 30], 
        lonaxis_range=[lon - 30, lon + 30], 
        center=dict(lat=lat, lon=lon), 
        projection_scale=1.5 
    )

    st.plotly_chart(fig, use_container_width=True)

# --- Robust Data Fetching with Coordinate Check and Uniqueness Check ---
def fetch_mystery_country():
    """
    Fetches filtered country data, removes microstates, and selects one country randomly.
    Includes checks for valid coordinates and, importantly, uniqueness within the session.
    """
    fields = "name,capital,flags,population,region,currencies,borders,cca2,latlng"
    full_url = f"{REST_COUNTRIES_API_BASE}/all?fields={fields}"

    try:
        response = requests.get(full_url)
        response.raise_for_status()

        all_countries_data = response.json()
        
        # Filter: Population >= 1,000,000
        filtered_countries = [
            country for country in all_countries_data 
            if country.get('population', 0) >= 1000000
        ]

        if not filtered_countries:
            st.error("Error: No countries found after filtering!")
            return None
        
        # --- EDGE CASE FIX: Loop to ensure we get a country with valid coordinates and is UNUSED ---
        MAX_RETRIES = 100
        for i in range(MAX_RETRIES):
            mystery_country = random.choice(filtered_countries)
            country_name = mystery_country['name']['common']
            
            # Check 1: Is this country already used in the session?
            if country_name in st.session_state.used_countries:
                continue # Skip to the next random choice
            
            # 2. Get ISO Code (needed for World Bank API)
            country_iso_code = mystery_country.get('cca2', 'XX')
            
            # 3. Check World Bank Data
            world_bank_clue = get_world_bank_clue(country_iso_code)
            
            # Check 2: Does this country have valid coordinates?
            if world_bank_clue['lat'] is not None and world_bank_clue['lon'] is not None:
                # Success! Found a valid, unused country.
                if 'borders' not in mystery_country or len(mystery_country['borders']) == 0:
                    mystery_country['borders'] = ['Island'] 
                
                st.session_state._wb_clue = world_bank_clue 
                return mystery_country
            
            # If coordinates were None, the loop continues to the next retry

        st.error("Error: Failed to find a new, valid country after 100 attempts. Resetting used country list.")
        st.session_state.used_countries = set() # Emergency reset
        return fetch_mystery_country() # Try again with a clear list

    except requests.exceptions.RequestException as e:
        st.error(f"A connection error occurred with REST Countries API: {e}")
        return None


# --- 3. STREAMLIT APP LOGIC ---

# Initialize Session State
if 'game_started' not in st.session_state: st.session_state.game_started = False
if 'mystery_country' not in st.session_state: st.session_state.mystery_country = None
if 'clue_index' not in st.session_state: st.session_state.clue_index = 0
if 'clues_list' not in st.session_state: st.session_state.clues_list = []
if 'game_ended' not in st.session_state: st.session_state.game_ended = False
if 'guess_input' not in st.session_state: st.session_state.guess_input = ""
if 'win' not in st.session_state: st.session_state.win = False
if 'current_streak' not in st.session_state: st.session_state.current_streak = 0
if 'accumulated_points' not in st.session_state: st.session_state.accumulated_points = 0
if 'user_name' not in st.session_state: st.session_state.user_name = None
if 'exit_message' not in st.session_state: st.session_state.exit_message = None
if '_wb_clue' not in st.session_state: st.session_state._wb_clue = None # Temporary storage
if 'last_streak' not in st.session_state: st.session_state.last_streak = 0 # Stores streak before loss
if 'used_countries' not in st.session_state: st.session_state.used_countries = set() # Track used countries

ALTERNATE_NAMES = {
    'netherlands': ['holland', 'the netherlands'], 
    'united kingdom': ['uk', 'britain', 'england'],
    'united states': ['usa', 'us', 'america'], 
    'united arab emirates': ['uae', 'emirates'],
    'russian federation': ['russia'], 
    'south korea': ['korea', 'rok'], 
    'north korea': ['dprk'], 
    'syria': ['syrian arab republic'], 
    'laos': ['lao pdr'],
    'vietnam': ['viet nam'], 
    'iran': ['persia'], 
    'türkiye': ['turkey'], 
    'czechia': ['czech republic']
}

# --- HANDLER FOR NAME SUBMISSION ---
def handle_name_submit():
    """Captures and stores the user's name to start the game."""
    if st.session_state.name_input:
        st.session_state.user_name = st.session_state.name_input
        initialize_game() # Proceed to game setup

def initialize_game():
    """Fetches new data and resets session state for a new game."""
    st.session_state.exit_message = None 
    
    with st.spinner('Fetching a mystery country...'):
        country = fetch_mystery_country()
        st.session_state.mystery_country = country
        
    if country:
        # --- Use pre-fetched World Bank data ---
        world_bank_data = st.session_state._wb_clue
        # --------------------------------------------------
        
        # Prepare Clues
        iso = country.get('cca2', 'XX')
        border_names = get_border_names(country.get('borders', []))
        currency = list(country.get('currencies', {'ABC':{}}).keys())[0]
        
        # --- DIFFICULTY SEQUENCE (The Funnel) ---
        st.session_state.clues_list = [
            f"Clue 1 (10 Points Potential): Approximate Location (Textual):\n"
            f"1) Location: {world_bank_data['location']}\n"
            f"2) Economic Classification: {world_bank_data['classification']}", 
            
            f"Clue 2 (8 Points Potential): Population: **{country['population']:,}**.",
            f"Clue 3 (6 Points Potential): Currency Code: **{currency}**.",
            f"Clue 4 (4 Points Potential): Neighbors: **{border_names}**.", 
            f"Clue 5 (2 Points Potential): Capital City: **{country.get('capital', ['Unknown'])[0]}**.",
        ]
        
        st.session_state.lat = world_bank_data['lat']
        st.session_state.lon = world_bank_data['lon']
        st.session_state.game_started = True
        st.session_state.clue_index = 0
        st.session_state.game_ended = False
        st.session_state.guess_input = "" # Clear input

def handle_exit():
    """Clears the session and prompts the user to close the tab."""
    final_streak_value = st.session_state.current_streak 
    final_points_value = st.session_state.accumulated_points
    
    st.session_state.game_started = False
    st.session_state.game_ended = False
    st.session_state.current_streak = 0 
    st.session_state.accumulated_points = 0
    st.session_state.user_name = None
    st.session_state.used_countries = set() # RESET USED COUNTRIES ON EXIT
    
    # Set the exit message with personalized score
    exit_msg = (
        f"Thank you for playing TerraCaughta! You finished with a final score of "
        f"**{final_points_value} points** and a streak of **{final_streak_value} countries**. "
        f"You can now safely close this tab."
    )
    st.session_state.exit_message = exit_msg

def handle_next_clue():
    """Advances the clue index when the dedicated 'Next Clue' button is pressed."""
    st.session_state.guess_input = "" 
    
    if st.session_state.clue_index < len(st.session_state.clues_list) - 1:
        st.session_state.clue_index += 1
    else:
        # User clicks Next Clue when on the last clue: End the game as a skip/loss
        st.session_state.game_ended = True
