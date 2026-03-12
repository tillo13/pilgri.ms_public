#!/usr/bin/env python3
"""
UI Icon Generation Script
Generates Mars-material style icons to replace all emoji icons across the site.

Usage:
    python tools/generate_ui_icons.py              # Generate all icons
    python tools/generate_ui_icons.py --category navigation  # Generate specific category
    python tools/generate_ui_icons.py --list       # List all icons to generate

Icon Categories:
    - navigation: Theme toggle, logout, edit, info icons
    - status: Success, error, warning, processing icons
    - rarity: Legendary, rare, uncommon, common discovery icons
    - stats: Leadership, strategy, exploration, logistics, charisma
    - activity: Income, expense, expedition, extraction icons
    - environment: Sun, moon, dust storm, temperature, satellite
    - ui: Empty states, filters, tabs, misc UI elements
"""

import sys
import os
import logging
import time
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# MARS-MATERIAL STYLE ICON PROMPTS
# Style: Carved from Martian rock, subtle Sepolia crystal accents
# All icons should feel like ancient Martian artifacts
# ============================================================================

UI_ICON_PROMPTS = {
    # -------------------------------------------------------------------------
    # NAVIGATION & UI ACTIONS
    # -------------------------------------------------------------------------
    'icon_moon_theme': (
        "Cartoon video game icon with bold outlines: crescent moon carved from "
        "reddish-brown Martian stone, subtle blue-purple crystal veins glowing faintly, "
        "weathered rocky texture, isolated on transparent red Mars dust background, "
        "32x32 pixel art style, vibrant colors, video game UI icon"
    ),
    'icon_sun_theme': (
        "Cartoon video game icon with bold outlines: stylized sun disk carved from "
        "golden-orange Martian sandstone, radiating stone rays, small embedded "
        "glowing amber crystals at center, ancient artifact feel, isolated on "
        "transparent red Mars dust background, 32x32 pixel art style, video game UI icon"
    ),
    'icon_edit_pencil': (
        "Cartoon video game icon with bold outlines: stylus or chisel tool carved from "
        "dark Martian basalt rock, tip has faint blue crystal glow, weathered handle "
        "wrapped in worn leather strips, isolated on red Martian terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_logout_door': (
        "Cartoon video game icon with bold outlines: ancient airlock door carved into "
        "red Martian rock face, circular hatch with weathered metal hinges, small "
        "blue crystal status light, dust particles, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_info': (
        "Cartoon video game icon with bold outlines: circular Martian stone tablet with "
        "carved 'i' symbol, glowing faint blue-purple from embedded Sepolia crystal, "
        "ancient informational marker feel, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # STATUS INDICATORS
    # -------------------------------------------------------------------------
    'icon_success_check': (
        "Cartoon video game icon with bold outlines: checkmark carved from polished "
        "green-tinted Martian mineral, glowing softly with success energy, geometric "
        "angular design, crystalline edges, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_error_x': (
        "Cartoon video game icon with bold outlines: X mark carved from cracked "
        "red-black volcanic Martian rock, faint orange ember glow in cracks, "
        "jagged broken edges, danger symbol feel, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_warning_alert': (
        "Cartoon video game icon with bold outlines: triangular warning sign carved "
        "from amber-orange Martian crystal, exclamation mark etched in center, "
        "pulsing warm glow, ancient hazard marker, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_processing_hourglass': (
        "Cartoon video game icon with bold outlines: hourglass carved from translucent "
        "Martian quartz crystal, blue-purple Sepolia sand flowing inside, ancient "
        "timekeeper artifact, glowing faintly, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # RARITY TIER ICONS (for discoveries)
    # -------------------------------------------------------------------------
    'icon_rarity_legendary': (
        "Cartoon video game icon with bold outlines: radiant star-shaped crystal "
        "carved from pure golden-orange Martian amber, multiple facets catching light, "
        "brilliant inner glow, ancient legendary artifact marker, epic feel, "
        "isolated on red Mars terrain, 32x32 pixel art style, video game UI icon"
    ),
    'icon_rarity_rare': (
        "Cartoon video game icon with bold outlines: faceted gem carved from deep "
        "purple-blue Sepolia crystal, diamond shape, inner light pulsing, "
        "valuable artifact marker, mystical glow, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_rarity_uncommon': (
        "Cartoon video game icon with bold outlines: leaf or sprout shape carved from "
        "green-tinted Martian mineral with copper veins, organic curved design, "
        "subtle healthy glow, growth symbol, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_rarity_common': (
        "Cartoon video game icon with bold outlines: simple cube or crate shape carved "
        "from weathered tan Martian sandstone, basic storage container, humble but "
        "solid design, dust-covered, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # CAPTAIN STAT ICONS
    # -------------------------------------------------------------------------
    'icon_stat_leadership': (
        "Cartoon video game icon with bold outlines: crown or command insignia carved "
        "from polished dark Martian obsidian, gold crystal inlays forming rank marks, "
        "authoritative military feel, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_stat_strategy': (
        "Cartoon video game icon with bold outlines: target crosshairs or tactical "
        "scope carved from precision-cut Martian crystal, geometric angular design, "
        "glowing blue center dot, military precision feel, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_stat_exploration': (
        "Cartoon video game icon with bold outlines: compass rose carved from layered "
        "Martian sandstone and crystal, cardinal points marked with small gems, "
        "adventurer's tool feel, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_stat_logistics': (
        "Cartoon video game icon with bold outlines: cargo crate or supply container "
        "carved from reinforced Martian rock, metal strapping details, organized "
        "storage feel, practical and sturdy, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_stat_charisma': (
        "Cartoon video game icon with bold outlines: starburst or sparkle pattern "
        "carved from iridescent Martian crystal, multiple radiating points, "
        "charming magical glow effect, personality symbol, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # ACTIVITY LOG ICONS
    # -------------------------------------------------------------------------
    'icon_activity_income': (
        "Cartoon video game icon with bold outlines: upward arrow with plus sign "
        "carved from green-tinted growth crystal, rising energy feel, prosperity "
        "symbol, glowing softly, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_activity_expense': (
        "Cartoon video game icon with bold outlines: downward arrow carved from "
        "red-orange Martian volcanic rock, spending/cost symbol, subtle ember glow, "
        "transaction marker, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_activity_expedition': (
        "Cartoon video game icon with bold outlines: small rocket ship carved from "
        "sleek Martian basalt with blue crystal engine glow, launching upward pose, "
        "exploration symbol, dynamic feel, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_activity_construction': (
        "Cartoon video game icon with bold outlines: construction crane or scaffolding "
        "carved from industrial Martian iron-rock, building in progress feel, "
        "amber status lights, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_activity_extraction': (
        "Cartoon video game icon with bold outlines: crystal being pulled from rock, "
        "extraction process, Sepolia shard emerging from Martian stone, energy lines "
        "radiating outward, harvesting symbol, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # ENVIRONMENT & MARS STATUS
    # -------------------------------------------------------------------------
    'icon_env_sun_power': (
        "Cartoon video game icon with bold outlines: stylized sun with solar panel "
        "rays carved from golden Martian crystal, energy generation symbol, "
        "warm power glow, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_env_temperature': (
        "Cartoon video game icon with bold outlines: thermometer carved from "
        "gradient Martian crystal (blue cold to red hot), temperature gauge, "
        "environmental monitor symbol, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_env_satellite': (
        "Cartoon video game icon with bold outlines: orbital satellite dish carved "
        "from metallic Martian iron-stone, antenna arrays, communication symbol, "
        "blue signal waves emanating, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_env_dust_storm': (
        "Cartoon video game icon with bold outlines: swirling dust cloud carved from "
        "layered tan and orange Martian sandstone, turbulent weather symbol, "
        "dynamic spiral pattern, danger feel, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # UI EMPTY STATES & TABS
    # -------------------------------------------------------------------------
    'icon_empty_discoveries': (
        "Cartoon video game icon with bold outlines: treasure map scroll carved from "
        "weathered Martian parchment-stone, rolled edges, 'X marks spot' symbol, "
        "adventure awaits feel, isolated on red Mars background, "
        "48x48 pixel art style, video game UI icon"
    ),
    'icon_empty_equipment': (
        "Cartoon video game icon with bold outlines: empty tool rack or equipment "
        "stand carved from Martian industrial rock, waiting for gear, workshop feel, "
        "practical design, isolated on Mars terrain, "
        "48x48 pixel art style, video game UI icon"
    ),
    'icon_empty_expeditions': (
        "Cartoon video game icon with bold outlines: telescope or spyglass carved from "
        "polished Martian crystal and bronze-rock, looking to horizon, exploration "
        "awaits symbol, isolated on red Mars background, "
        "48x48 pixel art style, video game UI icon"
    ),
    'icon_empty_power': (
        "Cartoon video game icon with bold outlines: lightning bolt carved from "
        "blue-white energy crystal, power symbol, electrical feel, waiting for "
        "energy generation, isolated on Mars terrain, "
        "48x48 pixel art style, video game UI icon"
    ),
    'icon_tab_map': (
        "Cartoon video game icon with bold outlines: folded map carved from "
        "Martian terrain layers showing topography, navigation tool, explorer's "
        "essential gear, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_tab_tools': (
        "Cartoon video game icon with bold outlines: wrench and hammer crossed, "
        "carved from dark Martian iron-stone, workshop tools symbol, practical "
        "engineering feel, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_tab_wallet': (
        "Cartoon video game icon with bold outlines: small pouch or cache carved from "
        "worn Martian leather-stone, Sepolia crystals peeking out, resource storage "
        "symbol, isolated on red Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # MISCELLANEOUS UI
    # -------------------------------------------------------------------------
    'icon_shard_gem': (
        "Cartoon video game icon with bold outlines: Sepolia shard crystal carved "
        "from pure purple-blue energy crystal, faceted gem shape, inner glow pulsing, "
        "valuable currency symbol, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_timer_clock': (
        "Cartoon video game icon with bold outlines: circular clock face carved from "
        "Martian stone with crystal hour markers, time tracking symbol, ancient "
        "chronometer feel, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_mountain_terrain': (
        "Cartoon video game icon with bold outlines: mountain peak carved from "
        "layered red-brown Martian rock, terrain symbol, expedition destination, "
        "majestic landmark feel, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_location_pin': (
        "Cartoon video game icon with bold outlines: map marker pin carved from "
        "red Martian crystal with golden tip, location symbol, destination marker, "
        "navigation essential, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_calendar_date': (
        "Cartoon video game icon with bold outlines: calendar page carved from "
        "Martian slate stone, date marking symbol, schedule tracker, "
        "organized planning feel, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_camera_photo': (
        "Cartoon video game icon with bold outlines: vintage camera carved from "
        "dark Martian basalt with crystal lens, photo capture symbol, "
        "documentation tool, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_chat_message': (
        "Cartoon video game icon with bold outlines: speech bubble carved from "
        "translucent Martian crystal, communication symbol, conversation marker, "
        "soft inner glow, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_signal_transmission': (
        "Cartoon video game icon with bold outlines: radio tower with signal waves "
        "carved from Martian iron-stone and crystal, transmission symbol, "
        "communication beacon, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_astronaut_avatar': (
        "Cartoon video game icon with bold outlines: astronaut helmet carved from "
        "white Martian mineral with reflective visor crystal, explorer symbol, "
        "human presence on Mars, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # ADDITIONAL ICONS - BATCH 2
    # -------------------------------------------------------------------------
    'icon_rocket_launch': (
        "Cartoon video game icon with bold outlines: sleek rocket ship carved from "
        "dark Martian basalt with flame exhaust in orange crystal, launch symbol, "
        "expedition vessel, space exploration, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_telescope': (
        "Cartoon video game icon with bold outlines: observatory telescope carved from "
        "dark Martian rock with crystal lens element, exploration tool, "
        "discovery instrument, gazing at stars, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_user_profile': (
        "Cartoon video game icon with bold outlines: simple human silhouette bust carved from "
        "sandy Martian sandstone, profile portrait, user avatar placeholder, "
        "colonist symbol, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_hammer_building': (
        "Cartoon video game icon with bold outlines: construction hammer carved from "
        "dark Martian iron-stone, building tool, under construction, "
        "work in progress symbol, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_dice_random': (
        "Cartoon video game icon with bold outlines: six-sided die carved from "
        "polished Martian mineral with crystal dot inlays, chance symbol, "
        "random outcome, gambling element, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_video_film': (
        "Cartoon video game icon with bold outlines: film reel or clapboard carved from "
        "dark Martian slate, video recording symbol, movie creation, "
        "animation tool, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_gift_box': (
        "Cartoon video game icon with bold outlines: wrapped gift box carved from "
        "warm amber Martian crystal with ribbon detail, reward symbol, "
        "bonus prize, celebration gift, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_wrench_repair': (
        "Cartoon video game icon with bold outlines: mechanical wrench carved from "
        "dark Martian iron-stone, repair tool, maintenance symbol, "
        "fix and upgrade, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_shopping_cart': (
        "Cartoon video game icon with bold outlines: wheeled cart carved from "
        "reddish Martian rock with crystal accents, shopping symbol, "
        "purchase item, store element, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_shop_storefront': (
        "Cartoon video game icon with bold outlines: small shop building carved from "
        "Martian sandstone with awning detail, store symbol, "
        "marketplace, trading post, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_microscope_lab': (
        "Cartoon video game icon with bold outlines: laboratory microscope carved from "
        "dark Martian basalt with crystal eyepiece, science tool, "
        "research analysis, extraction device, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_crown_leadership': (
        "Cartoon video game icon with bold outlines: royal crown carved from "
        "golden Martian mineral with gem inlays, leadership symbol, "
        "commander rank, authority badge, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_target_strategy': (
        "Cartoon video game icon with bold outlines: bullseye target carved from "
        "layered Martian stone rings with crystal center, precision symbol, "
        "strategy focus, tactical aim, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_compass_exploration': (
        "Cartoon video game icon with bold outlines: navigation compass carved from "
        "Martian brass-stone with crystal needle, exploration tool, "
        "direction finder, pathfinding symbol, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_sparkle_charisma': (
        "Cartoon video game icon with bold outlines: starburst sparkle carved from "
        "brilliant Martian crystal, charisma symbol, charm effect, "
        "magic shine, personality glow, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_home_base': (
        "Cartoon video game icon with bold outlines: dome habitat carved from "
        "reddish Martian rock with window crystal, home base symbol, "
        "colony shelter, main headquarters, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_tower_structures': (
        "Cartoon video game icon with bold outlines: communication tower carved from "
        "Martian iron-stone with crystal antenna, structures symbol, "
        "infrastructure building, colony tower, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_stopwatch_duration': (
        "Cartoon video game icon with bold outlines: stopwatch timer carved from "
        "Martian bronze-stone with crystal face, time duration symbol, "
        "countdown tracker, speed measurement, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_mountain_type': (
        "Cartoon video game icon with bold outlines: jagged mountain peak carved from "
        "layered reddish Martian rock, terrain type symbol, "
        "landscape feature, geographic marker, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_link_chain': (
        "Cartoon video game icon with bold outlines: chain links carved from "
        "Martian iron-stone with subtle crystal joints, connection symbol, "
        "external link, reference URL, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_play_button': (
        "Cartoon video game icon with bold outlines: triangular play arrow carved from "
        "bright Martian crystal, video play symbol, start action, "
        "media control, begin playback, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_construction_crane': (
        "Cartoon video game icon with bold outlines: construction crane arm carved from "
        "dark Martian iron-stone, building in progress symbol, "
        "under development, infrastructure work, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_point_down': (
        "Cartoon video game icon with bold outlines: pointing hand or arrow carved from "
        "sandy Martian sandstone pointing downward, attention symbol, "
        "call to action, look here indicator, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_folder_upload': (
        "Cartoon video game icon with bold outlines: file folder carved from "
        "Martian slate stone with upload arrow, file management symbol, "
        "document storage, data transfer, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_lightning_power': (
        "Cartoon video game icon with bold outlines: lightning bolt carved from "
        "bright yellow Martian crystal, power energy symbol, "
        "electricity charge, energy source, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_chart_activity': (
        "Cartoon video game icon with bold outlines: bar chart graph carved from "
        "Martian slate with crystal data points, statistics symbol, "
        "activity log, analytics display, isolated on Mars background, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_box_package': (
        "Cartoon video game icon with bold outlines: storage crate box carved from "
        "Martian sandstone with crystal clasps, package symbol, "
        "inventory container, cargo hold, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),

    # -------------------------------------------------------------------------
    # BATCH 3 - EMOJI REPLACEMENT ICONS
    # For replacing remaining Unicode emojis across the site
    # -------------------------------------------------------------------------
    'icon_lock_closed': (
        "Cartoon video game icon with bold outlines: padlock carved from dark "
        "Martian iron-stone with crystal keyhole glowing faintly, locked/restricted "
        "symbol, security marker, ancient vault lock feel, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_star_milestone': (
        "Cartoon video game icon with bold outlines: five-pointed star carved from "
        "golden-orange Martian crystal, achievement milestone symbol, special bonus "
        "marker, radiant glow effect, important feature indicator, isolated on Mars, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_gear_settings': (
        "Cartoon video game icon with bold outlines: mechanical gear cog carved from "
        "dark Martian iron-stone, settings/configuration symbol, adjustable mechanism, "
        "technical controls, subtle metallic sheen, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_vehicle_rover': (
        "Cartoon video game icon with bold outlines: six-wheeled Mars rover carved from "
        "reddish Martian rock with crystal headlights, exploration vehicle, rugged "
        "all-terrain design, expedition transport, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_vehicle_drone': (
        "Cartoon video game icon with bold outlines: flying quadcopter drone carved from "
        "dark Martian basalt with glowing blue crystal rotors, aerial scout, "
        "fast reconnaissance unit, hovering pose, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_vehicle_buggy': (
        "Cartoon video game icon with bold outlines: fast racing buggy carved from "
        "sleek Martian stone with large wheels, speed vehicle, all-terrain racer, "
        "sporty design with crystal accents, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_magnifier_discovery': (
        "Cartoon video game icon with bold outlines: magnifying glass carved from "
        "Martian crystal with bronze-stone handle, discovery search symbol, "
        "find hidden items, investigation tool, clear lens glow, isolated on Mars, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_tornado_dust': (
        "Cartoon video game icon with bold outlines: swirling tornado funnel carved from "
        "layered tan and orange Martian sandstone, dust storm hazard symbol, "
        "weather danger, spinning vortex design, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_pickaxe_mining': (
        "Cartoon video game icon with bold outlines: mining pickaxe carved from "
        "dark Martian iron-stone with crystal-tipped head, extraction tool, "
        "resource gathering, digging implement, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_fuel_pump': (
        "Cartoon video game icon with bold outlines: fuel pump or canister carved from "
        "metallic Martian iron-stone with glowing amber liquid indicator, energy "
        "resource, vehicle fuel symbol, industrial design, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_cargo_capacity': (
        "Cartoon video game icon with bold outlines: open cargo hold or container "
        "carved from reinforced Martian rock, storage space symbol, capacity "
        "indicator, practical hauling design, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_speed_fast': (
        "Cartoon video game icon with bold outlines: motion lines or speedometer "
        "carved from bright Martian crystal, speed boost symbol, velocity "
        "indicator, fast movement, dynamic energy feel, isolated on Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_night_moon': (
        "Cartoon video game icon with bold outlines: crescent moon with stars carved "
        "from cool blue-purple Martian crystal, night time symbol, nocturnal "
        "generation, evening hours indicator, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_income_coins': (
        "Cartoon video game icon with bold outlines: stack of Sepolia crystal coins "
        "carved from purple-blue Martian mineral, income/wealth symbol, currency "
        "pile, passive earnings indicator, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_value_diamond': (
        "Cartoon video game icon with bold outlines: faceted diamond shape carved from "
        "brilliant Martian crystal, high value symbol, precious gem, quality "
        "indicator, sparkling facets, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_rare_sparkle': (
        "Cartoon video game icon with bold outlines: sparkling star burst carved from "
        "purple-pink Martian crystal, rare find symbol, special discovery "
        "indicator, magical glow effect, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_checkmark_done': (
        "Cartoon video game icon with bold outlines: simple green checkmark tick symbol "
        "made of two thick lines forming a V shape at an angle, carved from emerald-green "
        "Martian crystal, approval symbol, YES indicator, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon, no background objects"
    ),

    # -------------------------------------------------------------------------
    # BATCH 4 - REMAINING ADMIN/MENU ICONS
    # -------------------------------------------------------------------------
    'icon_email_envelope': (
        "Cartoon video game icon with bold outlines: sealed envelope carved from "
        "tan Martian parchment stone with red crystal wax seal, mail/message symbol, "
        "communication notification, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_tree_progression': (
        "Cartoon video game icon with bold outlines: stylized tech tree or skill tree "
        "with branching nodes carved from copper-green Martian mineral, progression "
        "path symbol, growth chart, upgrade tree, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_palette_art': (
        "Cartoon video game icon with bold outlines: artist palette with color dots "
        "carved from colorful Martian minerals, creative design symbol, customization "
        "tool, art and style indicator, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_book_lore': (
        "Cartoon video game icon with bold outlines: ancient book or tome carved from "
        "dark Martian stone with glowing rune on cover, knowledge/lore symbol, "
        "guide and documentation, wisdom repository, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_clipboard_list': (
        "Cartoon video game icon with bold outlines: clipboard with checklist carved from "
        "tan Martian slate with crystal clip, notes/changelog symbol, task list, "
        "documentation board, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
    'icon_trash_delete': (
        "Cartoon video game icon with bold outlines: trash can or waste bin carved from "
        "dark reddish Martian rock with lid, delete symbol, remove/discard action, "
        "simple waste container design, isolated on red Mars terrain, "
        "32x32 pixel art style, video game UI icon"
    ),
}

# Icon categories for selective generation
ICON_CATEGORIES = {
    'navigation': ['icon_moon_theme', 'icon_sun_theme', 'icon_edit_pencil',
                   'icon_logout_door', 'icon_info'],
    'status': ['icon_success_check', 'icon_error_x', 'icon_warning_alert',
               'icon_processing_hourglass'],
    'rarity': ['icon_rarity_legendary', 'icon_rarity_rare', 'icon_rarity_uncommon',
               'icon_rarity_common'],
    'stats': ['icon_stat_leadership', 'icon_stat_strategy', 'icon_stat_exploration',
              'icon_stat_logistics', 'icon_stat_charisma'],
    'activity': ['icon_activity_income', 'icon_activity_expense', 'icon_activity_expedition',
                 'icon_activity_construction', 'icon_activity_extraction'],
    'environment': ['icon_env_sun_power', 'icon_env_temperature', 'icon_env_satellite',
                    'icon_env_dust_storm'],
    'ui': ['icon_empty_discoveries', 'icon_empty_equipment', 'icon_empty_expeditions',
           'icon_empty_power', 'icon_tab_map', 'icon_tab_tools', 'icon_tab_wallet'],
    'misc': ['icon_shard_gem', 'icon_timer_clock', 'icon_mountain_terrain',
             'icon_location_pin', 'icon_calendar_date', 'icon_camera_photo',
             'icon_chat_message', 'icon_signal_transmission', 'icon_astronaut_avatar'],
    'batch2': ['icon_rocket_launch', 'icon_telescope', 'icon_user_profile',
               'icon_hammer_building', 'icon_dice_random', 'icon_video_film',
               'icon_gift_box', 'icon_wrench_repair', 'icon_shopping_cart',
               'icon_shop_storefront', 'icon_microscope_lab', 'icon_crown_leadership',
               'icon_target_strategy', 'icon_compass_exploration', 'icon_sparkle_charisma',
               'icon_home_base', 'icon_tower_structures', 'icon_stopwatch_duration',
               'icon_mountain_type', 'icon_link_chain', 'icon_play_button',
               'icon_construction_crane', 'icon_point_down', 'icon_folder_upload',
               'icon_lightning_power', 'icon_chart_activity', 'icon_box_package'],
    # Emoji replacement icons - the final batch to eliminate all Unicode emojis
    'batch3_emoji_replace': [
        'icon_lock_closed', 'icon_star_milestone', 'icon_gear_settings',
        'icon_vehicle_rover', 'icon_vehicle_drone', 'icon_vehicle_buggy',
        'icon_magnifier_discovery', 'icon_tornado_dust', 'icon_pickaxe_mining',
        'icon_fuel_pump', 'icon_cargo_capacity', 'icon_speed_fast',
        'icon_night_moon', 'icon_income_coins', 'icon_value_diamond',
        'icon_rare_sparkle', 'icon_checkmark_done'
    ],
    # Admin/menu icons - remaining emojis
    'batch4_admin_menu': [
        'icon_email_envelope', 'icon_tree_progression', 'icon_palette_art',
        'icon_book_lore', 'icon_clipboard_list'
    ],
}

# GCS path for icons
GCS_ICON_PATH = "ui/icons"

def generate_icon(icon_id: str, flux: FluxGenerator) -> dict:
    """Generate a single icon and upload to GCS"""
    from config import FLUX_MODEL

    if icon_id not in UI_ICON_PROMPTS:
        logger.error(f"Unknown icon: {icon_id}")
        return None

    prompt = UI_ICON_PROMPTS[icon_id]
    logger.info(f"Generating icon: {icon_id}")

    try:
        # Generate with Flux using text-to-image (like populate_shop_images.py)
        replicate_url = flux.client.run(
            FLUX_MODEL,
            input={'prompt': prompt}
        )

        if isinstance(replicate_url, list):
            temp_url = replicate_url[0]
        else:
            temp_url = str(replicate_url)

        if not temp_url:
            logger.error(f"Failed to generate {icon_id}")
            return None

        logger.info(f"Generated temp URL for {icon_id}")

        # Upload to GCS
        timestamp = int(time.time())
        gcs_filename = f"{GCS_ICON_PATH}/{icon_id}_{timestamp}.png"

        gcs_url = upload_blob_from_url(
            source_url=temp_url,
            destination_blob_name=gcs_filename,
            content_type="image/png"
        )

        if gcs_url:
            logger.info(f"Uploaded {icon_id} to GCS: {gcs_url}")
            return {
                'icon_id': icon_id,
                'gcs_url': gcs_url,
                'filename': gcs_filename
            }
        else:
            logger.error(f"Failed to upload {icon_id} to GCS")
            return None

    except Exception as e:
        logger.error(f"Error generating {icon_id}: {e}")
        return None


def generate_category(category: str, flux: FluxGenerator) -> list:
    """Generate all icons in a category"""
    if category not in ICON_CATEGORIES:
        logger.error(f"Unknown category: {category}")
        return []

    icons = ICON_CATEGORIES[category]
    results = []

    for icon_id in icons:
        result = generate_icon(icon_id, flux)
        if result:
            results.append(result)
        time.sleep(2)  # Rate limiting

    return results


def generate_all_icons(flux: FluxGenerator) -> list:
    """Generate all icons"""
    results = []
    total = len(UI_ICON_PROMPTS)

    for i, icon_id in enumerate(UI_ICON_PROMPTS.keys(), 1):
        logger.info(f"Progress: {i}/{total}")
        result = generate_icon(icon_id, flux)
        if result:
            results.append(result)
        time.sleep(2)  # Rate limiting

    return results


def list_icons():
    """List all icons to be generated"""
    print("\n=== UI Icons to Generate ===\n")

    for category, icons in ICON_CATEGORIES.items():
        print(f"\n{category.upper()} ({len(icons)} icons):")
        for icon_id in icons:
            print(f"  - {icon_id}")

    print(f"\n\nTotal: {len(UI_ICON_PROMPTS)} icons")


def main():
    parser = argparse.ArgumentParser(description='Generate UI icons for Pilgrims')
    parser.add_argument('--category', type=str, help='Generate only this category')
    parser.add_argument('--icon', type=str, help='Generate a single icon by ID')
    parser.add_argument('--list', action='store_true', help='List all icons')
    args = parser.parse_args()

    if args.list:
        list_icons()
        return

    # Initialize Flux
    flux = FluxGenerator()

    if args.icon:
        # Single icon
        result = generate_icon(args.icon, flux)
        if result:
            print(f"\nGenerated: {result['gcs_url']}")
    elif args.category:
        # Category
        results = generate_category(args.category, flux)
        print(f"\nGenerated {len(results)} icons in {args.category}")
        for r in results:
            print(f"  {r['icon_id']}: {r['gcs_url']}")
    else:
        # All icons
        results = generate_all_icons(flux)
        print(f"\n=== Generated {len(results)}/{len(UI_ICON_PROMPTS)} icons ===")
        for r in results:
            print(f"  {r['icon_id']}: {r['gcs_url']}")


if __name__ == '__main__':
    main()
