import streamlit as st
import requests
import random
import sys
import Levenshtein 
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature
import time

# --- 0. STREAMLIT PAGE CONFIGURATION ---
st.set_page_config(layout="wide", page_title="TerraCaughta", page_icon="🌎")

# --- 1. CONFIGURATION ---
REST_COUNTRIES_API_BASE = "https://restcountries.com/v3.1"
WORLD_BANK_API_BASE = "http://api.worldbank.org/v2/country"
MAX_MISTAKES = 3

# POINT SYSTEM: Points awarded for solving the puzzle at each clue level
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

# --- RESTORED: PLOTTING WITH MATPLOTLIB/CARTOPY ---
def plot_coordinate_clue(lat, lon):
    """Plots the coordinate on a Cartopy map (static image)."""
    if lat is None or lon is None:
        st.warning("Map Clue: Cannot plot due to missing coordinates.")
        return
        
    try:
        fig = plt.figure(figsize=(6, 6)) 
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree()) 
        ax.coastlines(resolution='50m', color='gray', linewidth=0.5)
        ax.add_feature(cartopy.feature.LAND, facecolor='#eeeeee')
        ax.set_global() 
        ax.gridlines(draw_labels=False, linewidth=0.5, color='black', alpha=0.3)
        ax.plot(lon, lat, color='red', marker='*', markersize=12, transform=ccrs.PlateCarree()) 
        plt.title(f"Clue 1: Center Point Location (Visual Aid)", fontsize=14)
        st.pyplot(fig) 
        plt.close(fig) 
    except Exception:
        st.error("Visualization Error: Could not generate Cartopy map plot.")

def fetch_mystery_country():
    """Fetches a random country with population > 1M."""
    fields = "name,capital,flags,population,region,currencies,borders,cca2,latlng"
    full_url = f"{REST_COUNTRIES_API_BASE}/all?fields={fields}"
    try:
        response = requests.get(full_url)
        response.raise_for_status()
        all_countries = response.json()
        filtered = [c for c in all_countries if c.get('population', 0) >= 1000000]
        if not filtered: return None
        
        country = random.choice(filtered)
        if 'borders' not in country or len(country['borders']) == 0: country['borders'] = ['Island'] 
        return country
    except Exception as e:
        st.error(f"API Error: {e}")
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


ALTERNATE_NAMES = {
    'netherlands': ['holland', 'the netherlands'], 'united kingdom': ['uk', 'britain', 'england'],
    'united states': ['usa', 'us', 'america'], 'united arab emirates': ['uae', 'emirates'],
    'russian federation': ['russia'], 'south korea': ['korea', 'rok'], 
    'north korea': ['dprk'], 'syria': ['syrian arab republic'], 'laos': ['lao pdr'],
    'vietnam': ['viet nam'], 'iran': ['persia'], 'türkiye': ['turkey'], 'czechia': ['czech republic']
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
        # Prepare Clues
        iso = country.get('cca2', 'XX')
        wb_data = get_world_bank_clue(iso)
        border_names = get_border_names(country.get('borders', []))
        currency = list(country.get('currencies', {'ABC':{}}).keys())[0]
        
        # --- DIFFICULTY SEQUENCE (The Funnel) ---
        st.session_state.clues_list = [
            f"Clue 1 (10 Points Potential): Approximate Location (Textual):\n"
            f"1) Location: {wb_data['location']}\n"
            f"2) Economic Classification: {wb_data['classification']}", 
            
            f"Clue 2 (8 Points Potential): Population: **{country['population']:,}**.",
            f"Clue 3 (6 Points Potential): Currency Code: **{currency}**.",
            f"Clue 4 (4 Points Potential): Neighbors: **{border_names}**.", 
            f"Clue 5 (2 Points Potential): Capital City: **{country.get('capital', ['Unknown'])[0]}**.",
        ]
        
        st.session_state.lat = wb_data['lat']
        st.session_state.lon = wb_data['lon']
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
        st.session_state.current_streak = 0 # STREAK RESET on loss/skip
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
    else:
        # Wrong guess moves to next clue
        if st.session_state.clue_index < len(st.session_state.clues_list) - 1:
            st.session_state.clue_index += 1
            st.toast(f"'{user_guess}' was incorrect. Next clue revealed!")
        else:
            # Wrong guess on last clue ends game
            st.session_state.game_ended = True 
            st.session_state.win = False
            st.session_state.current_streak = 0 # STREAK RESET on loss

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
        plot_coordinate_clue(st.session_state.lat, st.session_state.lon)
        st.caption("The map remains fixed throughout the game.")
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

    with col_msg:
        # Personalized Win/Loss Message
        points_gained_this_round = POINT_MAP.get(st.session_state.clue_index, 0)
        
        if st.session_state.get('win', False):
            # Personalized Success Message
            if st.session_state.current_streak > 1:
                st.success(f"🎉 Great going, {name}! You earned **{points_gained_this_round} points** this round and are on a streak of **{st.session_state.current_streak}** countries!")
            else:
                 st.success(f"🎉 CORRECT, {name}! You earned **{points_gained_this_round} points** this round!")
            st.balloons()
        else:
            # Personalized Failure Message
            st.error(f"💀 Oops, {name}, you didn't get it this time. The country was **{country['name']['common']}**.")
            
        st.markdown("---")
        
        # Final Streak and Points Display
        st.subheader(f"🔥 Final Streak: {st.session_state.current_streak}")
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
