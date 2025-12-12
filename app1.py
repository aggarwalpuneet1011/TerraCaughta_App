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
@st.cache_data(ttl=3600) # Cache the full country list for 1 hour to reduce API calls
def fetch_all_countries():
    """Fetches and filters the full list of countries once."""
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
        return filtered_countries
    except requests.exceptions.RequestException as e:
        st.error(f"FATAL API ERROR: Could not fetch country data: {e}")
        return []

def select_mystery_country(filtered_countries):
    """Selects a unique country with valid World Bank coordinates."""
    
    if not filtered_countries:
        return None
    
    MAX_RETRIES = 100
    for i in range(MAX_RETRIES):
        
        # Check if all possible countries have been used in this session
        if len(st.session_state.used_countries) >= len(filtered_countries):
            st.warning("You have guessed all available countries! Resetting list.")
            st.session_state.used_countries = set()
            # Loop will continue with fresh list
        
        mystery_country = random.choice(filtered_countries)
        country_name = mystery_country['name']['common']
        
        # Check 1: Is this country already used in the session?
        if country_name in st.session_state.used_countries:
            continue
        
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

    st.error("Error: Failed to find a new, valid country after 100 attempts.")
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
    
    # 1. Fetch country list (cached) and select a mystery country
    filtered_countries = fetch_all_countries()
    if not filtered_countries:
        # Stop game if we can't get data (this handles FATAL API ERROR early)
        st.session_state.mystery_country = None
        st.error("Cannot start game: Data unavailable. Check internet or API status.")
        return

    with st.spinner('Fetching a unique mystery country...'):
        country = select_mystery_country(filtered_countries)
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
            f"Clue 4 (4 Points Points Potential): Neighbors: **{border_names}**.", 
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
        st.session_state.win = False
        st.session_state.last_streak = st.session_state.current_streak # CAPTURE STREAK
        st.session_state.current_streak = 0 # STREAK RESET on loss/skip
        st.session_state.used_countries.add(st.session_state.mystery_country['name']['common']) # ADD COUNTRY TO USED LIST
        st.toast("Time's up! Game over (Skipped final clue).")


def handle_submit_guess():
    """Handles guess submission, updates points, and manages streak/game state."""
    user_guess = normalize_text(st.session_state.guess_input)
    
    if not user_guess:
        st.warning("Please enter a guess or use the 'Next Clue' button to skip.")
        return

    # 1. Match Logic
    country_name = st.session_state.mystery_country['name']['common']
    normalized_name = normalize_text(country_name)
    
    is_match = False
    if user_guess == normalized_name: is_match = True
    elif normalized_name in ALTERNATE_NAMES and user_guess in ALTERNATE_NAMES[normalized_name]: is_match = True
    elif len(user_guess) > 3 and Levenshtein.distance(user_guess, normalized_name) <= MAX_MISTAKES: is_match = True
    
    # 2. Handle Result
    if is_match:
        # Calculate and accumulate points
        points_awarded = POINT_MAP.get(st.session_state.clue_index, 0)
        st.session_state.accumulated_points += points_awarded
        
        st.session_state.game_ended = True
        st.session_state.win = True
        st.session_state.current_streak += 1 # STREAK INCREMENT on win
        st.session_state.used_countries.add(country_name) # ADD COUNTRY TO USED LIST
    else:
        # Wrong guess moves to next clue
        if st.session_state.clue_index < len(st.session_state.clues_list) - 1:
            st.session_state.clue_index += 1
            st.toast(f"'{user_guess}' was incorrect. Next clue revealed!")
        else:
            # Wrong guess on last clue ends game
            st.session_state.game_ended = True 
            st.session_state.win = False
            st.session_state.last_streak = st.session_state.current_streak # CAPTURE STREAK
            st.session_state.current_streak = 0 # STREAK RESET on loss
            st.session_state.used_countries.add(country_name) # ADD COUNTRY TO USED LIST

    st.session_state.guess_input = ""


# --- 4. UI RENDERER (Optimized) ---
st.title("🌎 TerraCaughta")
st.markdown("A daily geography challenge built for the web. Use clues to find the hidden country!")
st.markdown("---")

# Check for final exit state
if st.session_state.get('exit_message'):
    st.success(st.session_state.exit_message)
    st.stop() 

# --- NAME CAPTURE SCREEN (Appears first) ---
if st.session_state.user_name is None:
    st.subheader("Welcome to TerraCaughta!")
    st.markdown("Before we start, let's get your name so we can personalize your score tracking.")
    
    st.text_input(
        "Enter your name:",
        key="name_input",
        placeholder="Your Name",
        on_change=handle_name_submit # Triggers submission on Enter key
    )
    st.button("Start Game", on_click=handle_name_submit, type="primary")
    
    # If API load fails early, show the error here
    if st.session_state.mystery_country is None and st.session_state.game_started:
        st.error("Data Load Error: Could not initialize the game. Please try refreshing the app.")
    
    # Stop rendering the rest of the app until name is submitted
    st.stop() 


# --- GAME IN PROGRESS UI ---
if st.session_state.game_started and not st.session_state.game_ended:
    
    name = st.session_state.user_name
    
    st.markdown(f"**Hello, {name}!** | 🔥 Streak: **{st.session_state.current_streak}** | 💰 Points: **{st.session_state.accumulated_points}**")
    st.markdown("---")

    col_map, col_clues = st.columns([1, 1.5]) 

    # --- LEFT COLUMN: MAP (Visual Clue) ---
    with col_map:
        st.subheader("Visual Context (Zoomable)")
        plot_coordinate_clue(st.session_state.lat, st.session_state.lon)
        st.caption("Use the controls on the map to zoom in for more detail.")
        st.markdown("---")
    
    # --- RIGHT COLUMN: CLUES & INPUT ---
    with col_clues:
        
        # Clues Section
        st.subheader(f"Clues Revealed ({st.session_state.clue_index + 1} of 5)")
        
        with st.container(border=True):
            for clue in st.session_state.clues_list[:st.session_state.clue_index + 1]:
                st.markdown(f"**{clue}**")

        # Input Section
        st.markdown("**---**")
        st.markdown("#### Guess or Advance")
        
        st.text_input(
            "Enter your Country Guess:",
            key="guess_input",
            placeholder="Type country name...",
            on_change=handle_submit_guess
        )
        
        # Determine button labels
        guess_label = "Submit Guess"
        next_clue_label = "Next Clue"
        
        if st.session_state.clue_index == len(st.session_state.clues_list) - 2: 
            next_clue_label = "Last Clue"
        elif st.session_state.clue_index == len(st.session_state.clues_list) - 1: 
            next_clue_label = "End Game"
        
        # Use columns to place buttons side-by-side
        col_submit, col_next = st.columns([1, 1])
        
        with col_submit:
            st.button(guess_label, on_click=handle_submit_guess, type="primary") 
            
        with col_next:
            st.button(next_clue_label, on_click=handle_next_clue, type="secondary")


# --- END GAME SCREEN UI ---
if st.session_state.game_ended:
    country = st.session_state.mystery_country
    name = st.session_state.user_name

    col_msg, col_flag = st.columns([1.5, 1])

    # Determine which streak count to display for the final results (FIXED NAMEERROR SCOPE)
    display_streak = st.session_state.current_streak 
    if not st.session_state.win and st.session_state.last_streak > 0:
        display_streak = st.session_state.last_streak

    with col_msg:
        # Personalized Win/Loss Message
        points_gained_this_round = POINT_MAP.get(st.session_state.clue_index, 0)
        
        if st.session_state.get('win', False):
            # Win Message 
            if display_streak > 1:
                st.success(f"🎉 Great going, {name}! You earned **{points_gained_this_round} points** this round and are on a streak of **{display_streak}** countries!")
            else:
                 st.success(f"🎉 CORRECT, {name}! You earned **{points_gained_this_round} points** this round!")
            st.balloons()
            
        else:
            # Loss Message 
            if display_streak > 0:
                 st.error(f"💀 Your streak ended at **{display_streak}**! Oops, {name}, you didn't get it this time. The country was **{country['name']['common']}**.")
            else:
                st.error(f"💀 Oops, {name}, you didn't get it this time. The country was **{country['name']['common']}**.")
            
        st.markdown("---")
        
        # Final Streak and Points Display
        st.subheader(f"🔥 Final Streak: {display_streak}")
        st.subheader(f"💰 Total Points: {st.session_state.accumulated_points}")
        st.markdown("---")
        
        st.subheader("Final Clue Review:")
        
        with st.container(border=True):
            for clue in st.session_state.clues_list:
                st.markdown(f"- {clue}") 
        
    with col_flag:
        st.image(country['flags']['png'], caption=f"Flag of {country['name']['common']}")
        
        # Button Section
        col_play, col_exit = st.columns([1, 1])
        
        with col_play:
            st.button("Play Again", on_click=initialize_game, type="primary")
            
        with col_exit:
            st.button("EXIT", on_click=handle_exit, type="secondary")
