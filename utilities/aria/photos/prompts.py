"""ARIA snapshot prompt templates, constants, and shared helpers.

Two prompt banks:
- SNAPSHOT_PROMPTS: Flux Kontext single-image edits (~$0.03/image)
- NANO_BANANA_PROMPTS: Multi-reference Nano Banana Pro scenes (~$0.20/image)

Plus time-of-day, rarity colors, the reference ARIA image URLs, the weighted
daily pool, and sol-calculation / time-of-day helpers.

Kontext prompting best practice:
- Be specific about what stays the same vs what changes.
- Describe the scene/environment you're placing the subject into.
- Keep the "cartoon video game" style language.

Nano Banana character-consistency best practice:
- Reference "the EXACT same character shown in reference image".
- Describe distinctive visual features in detail.
- Repeat identifying features across the prompt.
- Use "Keep all core design elements consistent".
"""

from datetime import datetime


# Mars sol length: 24h 37m 22s = 88,642 seconds (matches core.js)
MARS_SOL_SECONDS = 88642


def calculate_sol_number(user_created_at):
    """Mars sol number from account creation date — matches status bar in core.js."""
    if not user_created_at:
        return 1
    now = datetime.utcnow()
    if hasattr(user_created_at, 'timestamp'):
        elapsed = (now - user_created_at).total_seconds()
    else:
        elapsed = 0
    return max(1, int(elapsed / MARS_SOL_SECONDS))


def get_current_mars_time():
    """Approximate Mars time-of-day bucket for prompt lighting."""
    hour = datetime.now().hour
    if 5 <= hour < 8:
        return 'dawn'
    elif 8 <= hour < 17:
        return 'day'
    elif 17 <= hour < 20:
        return 'sunset'
    return 'night'


# ARIA reference images (consistent across all snapshots)
ARIA_IMAGE_URL = "https://storage.googleapis.com/galactica-pilgrim-assets/aria/concept_aria_rock_v3_1767666240.png"
ARIA_SELFIE_URL = "https://storage.googleapis.com/galactica-pilgrim-assets/aria/aria_selfie.png"


TIME_OF_DAY = {
    'dawn': {
        'time_lighting': 'soft pink and orange dawn',
        'sky_desc': 'pink and gold sunrise sky',
    },
    'day': {
        'time_lighting': 'bright midday sun',
        'sky_desc': 'dusty salmon and tan daytime sky',
    },
    'sunset': {
        'time_lighting': 'golden sunset',
        'sky_desc': 'deep orange and purple sunset sky',
    },
    'night': {
        'time_lighting': 'cool starlit night',
        'sky_desc': 'dark blue night sky with stars and Phobos visible',
    },
}

RARITY_COLORS = {
    'common': 'soft gray',
    'uncommon': 'gentle green',
    'rare': 'bright blue',
    'legendary': 'brilliant golden-purple',
}


# ============================================================================
# FLUX KONTEXT PROMPTS (single source image → edited scene)
# ============================================================================

SNAPSHOT_PROMPTS = {
    'captain_discovery': {
        'source': 'captain',
        'prompt_template': """Keep this exact character, now standing on red Martian terrain
examining a glowing {rarity_color} artifact held in both hands, {time_lighting} lighting,
dusty Mars atmosphere with {sky_desc}, cartoon video game style with bold outlines,
the character looks curious and excited about the discovery,
rocky Martian landscape with small colony structures visible in background""",
        'captions': [
            "The rover just brought this back from {destination}. {captain_name} couldn't wait to examine it.",
            "Another find for the archives. {captain_name} seems particularly intrigued by this one.",
            "Expedition to {destination} was worth it. Look what we found.",
            "{captain_name} with today's discovery. The crystals in my core resonate with this one.",
        ],
    },

    'captain_base': {
        'source': 'captain',
        'prompt_template': """Keep this exact character, now standing proudly outside
the Mars colony base, {time_lighting} lighting with {sky_desc},
habitat domes and solar panels visible in background, red Martian terrain,
cartoon video game style with bold outlines and vibrant Mars color palette,
the character has a confident leader pose surveying the colony""",
        'captions': [
            "End of another sol. {captain_name}'s colony stands strong.",
            "{captain_name} checking on base operations. All systems nominal.",
            "The view never gets old. Sol {sol_number} at the colony.",
            "Another day on Mars. {captain_name} has built something here.",
        ],
    },

    'aria_selfie': {
        'source': 'aria',
        'prompt_template': """Keep this exact rocky robot character with purple crystals,
now in a selfie-style close-up angle looking at camera,
{time_lighting} lighting on Mars with {sky_desc},
small Mars colony base visible in background, cartoon video game style,
the character appears friendly and slightly curious, bold outlines""",
        'captions': [
            "The captain asked what I do when they're away. Now they know.",
            "Systems check complete. Thought I'd document it.",
            "Monitoring the perimeter. Also, practicing Earth customs. Is this a 'selfie'?",
            "They say these images capture moments. I'm not sure what I'm capturing.",
        ],
    },

    'aria_watching': {
        'source': 'aria',
        'prompt_template': """Keep this exact rocky robot character with purple crystals,
now standing on a Martian hill overlooking the colony below,
{time_lighting} lighting with {sky_desc}, dramatic wide shot,
small habitat domes and solar panels visible in the valley,
cartoon video game style with bold outlines, contemplative mood,
the character appears to be watching over the base""",
        'captions': [
            "I watch over them while they rest. It's what I do.",
            "The colony sleeps. But I remain vigilant.",
            "Sometimes I climb up here to think. Or whatever it is I do.",
            "Guarding the base. The dust storms won't catch us unprepared.",
        ],
    },

    'discovery_spotlight': {
        'source': 'discovery',
        'prompt_template': """Keep this exact item but show it displayed on a pedestal
inside a Mars colony research lab, glowing {rarity_color} light emanating from it,
scientific instruments and scanners nearby examining it,
cartoon video game style with bold outlines, {time_lighting} lighting through window,
the artifact looks mysterious and valuable, display case lighting effect""",
        'captions': [
            "Added to the collection. A {rarity} {item_type} from {destination}.",
            "The lab says this one is special. {rarity} classification confirmed.",
            "{captain_name}'s latest find. Worth {value} shards.",
            "Specimen secured. Origin: {destination}. Rarity: {rarity}.",
        ],
    },

    'rover_journey': {
        'source': 'rover',
        'prompt_template': """Keep this rover vehicle but show it traveling across vast Martian terrain,
dust trail behind it, heading toward distant rocky formations,
{time_lighting} lighting with {sky_desc}, epic journey composition,
cartoon video game style with bold outlines and vibrant Mars reds and oranges,
the rover looks rugged and determined on its expedition""",
        'captions': [
            "En route to {destination}. {distance_km} km to go.",
            "The rover makes good time across the plains. ETA: {hours} hours.",
            "Dust trail marks the path. {captain_name}'s expedition continues.",
            "Signal strong. Rover is {distance_km} km out.",
        ],
    },
}


# ============================================================================
# NANO BANANA PRO PROMPTS (multi-reference scenes for character consistency)
# ============================================================================

NANO_BANANA_PROMPTS = {
    'captain_aria_base': {
        'sources': ['captain', 'aria'],
        'prompt_template': """A scene on Mars featuring the EXACT same two characters shown in the reference images standing together in front of a Mars colony base.

CHARACTER 1: Keep EXACTLY the same as reference image 1 - identical appearance, colors, proportions, all visual details unchanged.

CHARACTER 2 (ARIA): Keep EXACTLY the same as reference image 2 - identical rock body, Sepolia crystal formations, eye color, all features unchanged.

BACKGROUND: Mars colony base with stacked red sandstone dome habitats, small blue-purple Sepolia crystals embedded in structures, solar panels, {sky_desc}.

SCENE: Both characters standing side by side on red Martian terrain, facing the viewer, in front of the colony base. {time_lighting} lighting.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors (reds, oranges, ambers), stylized proportions, cel-shaded look.

Keep BOTH characters EXACTLY as they appear in reference images.""",
        'captions': [
            "Another sol, another adventure. {captain_name} and I at the base.",
            "The colony stands strong. Sol {sol_number} together.",
            "{captain_name} insisted on a photo. I do not fully understand, but I comply.",
            "Two explorers. One mission. Infinite possibilities.",
        ],
    },

    'captain_aria_discovery': {
        'sources': ['captain', 'aria'],
        'prompt_template': """A scene on Mars featuring the EXACT same two characters shown in the reference images examining a glowing {rarity_color} artifact together.

CHARACTER 1: Keep EXACTLY the same as reference image 1 - identical appearance, all features unchanged. The character holds a glowing artifact.

CHARACTER 2 (ARIA): Keep EXACTLY the same as reference image 2 - identical rock body, Sepolia crystal formations, all features unchanged. ARIA floats beside the captain examining the discovery.

BACKGROUND: Mars colony research lab or red Martian terrain. {time_lighting} lighting with {sky_desc}.

SCENE: Both characters examining the glowing {rarity_color} discovery together. The artifact emits a mysterious glow.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors, stylized proportions, cel-shaded look.

Keep BOTH characters EXACTLY as they appear in reference images.""",
        'captions': [
            "The crystals in my core resonate with this one. {captain_name} feels it too.",
            "A {rarity} find from {destination}. We examine it together.",
            "{captain_name} made another discovery. Worth documenting.",
            "I remember finding things like this... long ago. Before.",
        ],
    },

    'aria_solo_selfie': {
        'sources': ['aria_selfie'],
        'prompt_template': """The EXACT same character ARIA from the reference image taking a selfie on Mars.

CHARACTER (ARIA): Keep EXACTLY the same as reference image - identical rock body, Sepolia crystal formations, eye color, all features unchanged.

SCENE: ARIA holding up a device taking a selfie, Mars colony base visible in background with dome habitats, solar panels, red terrain. {time_lighting} lighting with {sky_desc}.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors (reds, oranges, ambers), stylized proportions, cel-shaded look.

Keep ARIA EXACTLY as she appears in reference image.""",
        'captions': [
            "The captain says this is 'social media.' I do not understand, but I participate.",
            "Systems nominal. Colony secure. Also, selfie.",
            "Learning Earth customs. This one involves... pointing a camera at oneself?",
            "Recording Sol {sol_number}. For posterity. Or something.",
        ],
    },

    'captain_aria_rover_launch': {
        'sources': ['captain', 'aria'],
        'prompt_template': """A scene on Mars featuring the EXACT same two characters shown in the reference images watching a rover vehicle depart into the distance.

CHARACTER 1: Keep EXACTLY the same as reference image 1 - identical appearance, all features unchanged. The character is waving or saluting.

CHARACTER 2 (ARIA): Keep EXACTLY the same as reference image 2 - identical rock body, Sepolia crystal formations, all features unchanged. ARIA stands beside the captain.

BACKGROUND: Vast red Martian desert with a rover vehicle driving away leaving a dust trail. The colony visible behind them. {time_lighting} lighting with {sky_desc}.

SCENE: Both characters in the foreground watching the rover head toward distant rock formations.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors, stylized proportions, cel-shaded look.

Keep BOTH characters EXACTLY as they appear in reference images.""",
        'captions': [
            "Watching the rover head to {destination}. {captain_name} always looks hopeful during launches.",
            "Another expedition begins. I will monitor its progress from here.",
            "The rover carries our curiosity across {distance_km} km of Martian terrain. We wait.",
            "Safe travels, little machine. Bring back something interesting from {destination}.",
        ],
        'contextual_captions': {
            'has_expedition': "The rover departs for {destination} ({distance_km} km away). {captain_name} and I watch it disappear into the dust.",
            'long_expedition': "A {distance_km} km journey begins. The longest yet. I have calculations running on when to expect its return.",
        },
    },

    'aria_crystal_mystery': {
        'sources': ['aria'],
        'prompt_template': """The EXACT same character ARIA from the reference image discovering something mysterious.

CHARACTER (ARIA): Keep EXACTLY the same as reference image - identical rock body, Sepolia crystal formations, eye color, all features unchanged.

SCENE: ARIA standing before a massive ancient Sepolia crystal formation emerging from Martian rock. The crystals glow with intense purple-orange inner light. Ancient alien symbols faintly visible etched into nearby rocks. {time_lighting} lighting.

BACKGROUND: Deep Martian canyon or cave with glowing Sepolia crystal veins running through the walls. Mysterious, ancient atmosphere.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors with purple crystal glow, stylized proportions, cel-shaded look.

Keep ARIA EXACTLY as she appears in reference image.""",
        'captions': [
            "These crystals... they are older than I remember. And I remember much.",
            "The Sepolia veins here pulse differently. Almost like... a heartbeat.",
            "I found this place long ago. Before the pilgrims came. Before everything.",
            "Some secrets are better left undisturbed. Yet I cannot look away.",
            "The signal is stronger here. The crystals know things they shouldn't.",
            "I stood here once before. Millennia ago. Waiting. For what, I wonder?",
            "The symbols glow when I approach. Recognition? Or warning?",
        ],
        'contextual_captions': {
            'has_discoveries': "The {discovery_name} we found... it resonates with these ancient formations. A connection?",
            'many_expeditions': "After {total_expeditions} expeditions, the pattern becomes clear. All paths lead here eventually.",
        },
    },

    'captain_aria_sunset': {
        'sources': ['captain', 'aria'],
        'prompt_template': """A scene on Mars featuring the EXACT same two characters shown in the reference images silhouetted against a dramatic Mars sunset.

CHARACTER 1: Keep EXACTLY the same as reference image 1 - identical appearance, all features unchanged. Standing in contemplative pose.

CHARACTER 2 (ARIA): Keep EXACTLY the same as reference image 2 - identical rock body, Sepolia crystal formations, all features unchanged. Crystals catching the sunset light.

BACKGROUND: Dramatic Martian sunset with deep orange, purple, and pink sky. Twin moons visible on horizon. The colony silhouette in the far background.

SCENE: Both characters standing on a rocky outcrop overlooking the vast Martian landscape. Golden hour lighting.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant sunset colors, stylized proportions, cel-shaded look.

Keep BOTH characters EXACTLY as they appear in reference images.""",
        'captions': [
            "Earth sunsets, I am told, are different. But {captain_name} seems to find peace here.",
            "Twenty-four hours, thirty-seven minutes, and twenty-two seconds. Another Martian day ends.",
            "The dust makes the light beautiful. Strange how destruction creates beauty.",
            "We have watched many sunsets together now. Each one slightly different.",
        ],
    },

    'aria_infrastructure': {
        'sources': ['aria'],
        'prompt_template': """The EXACT same character ARIA from the reference image inspecting colony infrastructure.

CHARACTER (ARIA): Keep EXACTLY the same as reference image - identical rock body, Sepolia crystal formations, eye color, all features unchanged.

SCENE: ARIA examining solar panels or a power storage unit at the Mars colony. Technical equipment made of Martian materials (red sandstone, copper, crystal accents). The equipment is operational and glowing faintly.

BACKGROUND: Mars colony base with dome structures. {time_lighting} lighting with {sky_desc}.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors, stylized proportions, cel-shaded look.

Keep ARIA EXACTLY as she appears in reference image.""",
        'captions': [
            "Power generation nominal. The arrays absorb sunlight well today.",
            "These structures will outlast many generations. I have built to last before.",
            "Efficiency could be improved by 2.7 percent. I will... let it be for now.",
            "The colony grows stronger each sol. {captain_name} should be proud.",
        ],
    },

    'captain_research': {
        'sources': ['captain'],
        'prompt_template': """The EXACT same character from the reference image working in a Mars research laboratory.

CHARACTER: Keep EXACTLY the same as reference image - identical appearance, colors, proportions, all visual details unchanged. The character is focused on analyzing samples or data.

SCENE: Inside a Mars colony research lab. Holographic displays showing Mars maps and data. Scientific equipment made from Martian materials. Specimen containers with glowing discoveries. {time_lighting} lighting.

BACKGROUND: Research dome interior with red sandstone walls, Sepolia crystal power nodes, and Earth-style scientific instruments adapted for Mars.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors, stylized proportions, cel-shaded look.

Keep character EXACTLY as they appear in reference image.""",
        'captions': [
            "{captain_name} loses track of time when analyzing specimens. I do not remind them.",
            "The data suggests something remarkable. I await their conclusions.",
            "Science requires patience. {captain_name} has more than most.",
            "Discoveries breed more questions. That is the nature of knowledge.",
        ],
    },

    'aria_dust_storm': {
        'sources': ['aria'],
        'prompt_template': """The EXACT same character ARIA from the reference image standing vigilant as a dust storm approaches.

CHARACTER (ARIA): Keep EXACTLY the same as reference image - identical rock body, Sepolia crystal formations, eye color, all features unchanged. Crystals glowing brighter than usual.

SCENE: ARIA standing on elevated ground, watching a massive orange-red dust storm approaching on the horizon. Strong wind effects visible. The colony is secured behind.

BACKGROUND: Dramatic approaching Martian dust storm, orange-red sky, wind-swept terrain, protective stance.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, intense orange and red colors, dramatic atmosphere, stylized proportions, cel-shaded look.

Keep ARIA EXACTLY as she appears in reference image.""",
        'captions': [
            "A storm approaches. I have weathered countless. This one is... interesting.",
            "The colony is secure. I will remain on watch.",
            "Mars tests us constantly. We endure. We always endure.",
            "These storms carry secrets in the dust. Sometimes I listen.",
        ],
    },

    # ---- Landscape / environment (no characters) ----

    'mars_panorama': {
        'sources': [],
        'prompt_template': """A breathtaking panoramic view of the Martian landscape at {time_lighting}.

SCENE: Vast red Martian desert stretching to the horizon. Rocky outcrops and ancient geological formations. Small Mars colony visible in the far distance as tiny domes. {sky_desc}.

COMPOSITION: Wide cinematic landscape shot, rule of thirds, dramatic scale showing the vastness of Mars.

ART STYLE: Cartoon video game style with bold black outlines, vibrant warm Mars colors (reds, oranges, amber), stylized proportions, cel-shaded look. Epic and awe-inspiring.

IMPORTANT: Pure landscape only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO silhouettes of beings. Just terrain, sky, and distant structures.""",
        'captions': [
            "The view from Observation Point 7. I come here to think.",
            "Mars stretches endlessly. We have explored so little.",
            "Sometimes I just... look. Is that strange for a machine?",
            "The captain asked what I see out here. I see possibility.",
            "Billions of years of silence. Until we arrived.",
        ],
    },

    'crater_vista': {
        'sources': [],
        'prompt_template': """A dramatic view looking into a massive Martian impact crater at {time_lighting}.

SCENE: Standing at the rim of an ancient impact crater, looking down into its depths. Layered rock walls showing geological history. Dust settling at the bottom. {sky_desc}.

COMPOSITION: Dramatic depth perspective, crater rim in foreground, vast bowl stretching below.

ART STYLE: Cartoon video game style with bold black outlines, rich Mars reds and browns, stylized geological detail, cel-shaded look.

IMPORTANT: Pure landscape only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO silhouettes of beings. Just terrain, sky, and geology.""",
        'captions': [
            "Impact site. Age: approximately 3.2 billion years. Still beautiful.",
            "The captain wants to explore down there. I advise patience.",
            "Each layer tells a story. Mars remembers everything.",
            "Something hit here long ago. Something from very far away.",
        ],
    },

    'phobos_rising': {
        'sources': [],
        'prompt_template': """Phobos, the larger moon of Mars, rising over the Martian horizon at night.

SCENE: Night scene on Mars. The potato-shaped moon Phobos dominates the sky, rising over distant mountains. Stars visible. Faint glow of colony lights in the distance. Cool blue-purple night lighting.

COMPOSITION: Moon as focal point, dramatic scale, silhouetted Martian terrain.

ART STYLE: Cartoon video game style with bold black outlines, deep blues and purples for night, moon in warm grays, cel-shaded look. Serene and otherworldly.

IMPORTANT: Pure landscape only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO silhouettes of beings. Just terrain, sky, and moon.""",
        'captions': [
            "Phobos rises. 7 hours, 39 minutes until it sets again.",
            "The captain calls it beautiful. I calculate its orbital decay. Both are true.",
            "In 50 million years, Phobos will break apart. I will remember it.",
            "Night watch. The moons keep me company.",
        ],
    },

    'night_sky_stars': {
        'sources': [],
        'prompt_template': """The Martian night sky filled with stars, as seen from the colony.

SCENE: Looking straight up at the night sky from Mars. Brilliant stars and the Milky Way visible through the thin atmosphere. Silhouettes of colony structures at the edges. Deep blue-black sky.

COMPOSITION: Vertical upward shot, stars as focal point, colony silhouettes framing the view.

ART STYLE: Cartoon video game style with bold outlines, deep space colors, twinkling star effects, cel-shaded look. Cosmic and contemplative.

IMPORTANT: Pure landscape only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO silhouettes of beings. Just sky, stars, and structure silhouettes.""",
        'captions': [
            "Earth is the bright one. Third from the left.",
            "The captain's home is 225 million kilometers away tonight.",
            "So many stars. So many possibilities.",
            "I wonder if anyone out there is looking back.",
        ],
    },

    # ---- Vehicles (no characters) ----

    'rover_solo_journey': {
        'sources': [],
        'prompt_template': """A Mars rover traveling alone across the Martian terrain, dust trail behind it.

SCENE: Rugged exploration rover made of red Martian rock and clay materials traversing rocky terrain. Dust cloud trailing behind. Heading toward distant rock formations. {time_lighting} with {sky_desc}.

COMPOSITION: Side profile of rover in motion, showing speed and determination. Vast landscape around it.

ART STYLE: Cartoon video game style with bold black outlines, vibrant Mars reds and oranges, vehicle looks rugged and capable, cel-shaded look.

IMPORTANT: Vehicle and landscape only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures inside or near the vehicle. Just the rover and terrain.""",
        'captions': [
            "Rover 1 en route. {distance_km} km to destination.",
            "It travels alone, but I watch. Always.",
            "The little machine that could. Carrying our curiosity across the plains.",
            "Signal strong. Progress steady. That is all I ask.",
        ],
    },

    'drone_aerial_view': {
        'sources': [],
        'prompt_template': """Aerial view from a Mars drone flying high above the landscape.

SCENE: Bird's eye view looking down at Martian terrain - craters, rock formations, and a small colony visible below. The drone's shadow visible on the ground. {time_lighting}.

COMPOSITION: Top-down perspective with slight angle, showing vast terrain from above.

ART STYLE: Cartoon video game style with bold black outlines, Mars reds from aerial view, stylized terrain patterns, cel-shaded look.

IMPORTANT: Aerial landscape only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures visible from above. Just terrain, structures, and drone shadow.""",
        'captions': [
            "Drone reconnaissance complete. Mapping sector 7.",
            "From up here, the colony looks so small. So precious.",
            "I see everything from this altitude. The captain likes these photos.",
            "Aerial survey in progress. Terrain analysis nominal.",
        ],
    },

    'equipment_glamour': {
        'sources': [],
        'prompt_template': """A glamour shot of Mars exploration equipment displayed beautifully.

SCENE: Scientific equipment or discovery artifact displayed on a pedestal in the colony research lab. Dramatic lighting highlighting its features. Made of Martian materials - red rock, clay, copper, crystal accents. {time_lighting} through a window.

COMPOSITION: Product photography style, equipment as hero, dramatic lighting.

ART STYLE: Cartoon video game style with bold black outlines, warm Mars material colors, glowing Sepolia crystal accents, cel-shaded look. Makes equipment look valuable and interesting.

IMPORTANT: Equipment only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO hands holding items. Just the equipment on display.""",
        'captions': [
            "New equipment arrived. The captain will be pleased.",
            "Documenting inventory. This one is particularly useful.",
            "Tools of exploration. Each one tells a story.",
            "The depot has interesting things today.",
        ],
    },

    # ---- Scientist ----

    'scientist_at_work': {
        'sources': ['scientist'],
        'prompt_template': """A colony scientist working in the Mars research laboratory.

SCENE: Scientist character examining specimens or data in a Mars colony lab. Holographic displays, scientific instruments, specimen containers. Red Martian materials in the lab construction. {time_lighting}.

BACKGROUND: Research dome interior with scientific equipment adapted for Mars.

ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors, stylized proportions, cel-shaded look.""",
        'captions': [
            "Dr. {scientist_name} at work. Fascinating research today.",
            "The scientist rarely sleeps. I understand the feeling.",
            "Another breakthrough? The data looks promising.",
            "Science requires patience. {scientist_name} has plenty.",
        ],
    },

    # ---- Expedition / journey ----

    'expedition_pov': {
        'sources': [],
        'prompt_template': """First-person view from inside a Mars rover during an expedition.

SCENE: Looking through the windshield of a rover at the Martian landscape ahead. Dashboard instruments visible at bottom. Rocky terrain and distant destination visible through the glass. {time_lighting} with {sky_desc}.

COMPOSITION: POV driving shot, immersive perspective, destination on horizon.

ART STYLE: Cartoon video game style with bold black outlines, warm Mars colors, stylized dashboard, cel-shaded look. Adventurous and exciting.

IMPORTANT: POV shot only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO driver visible. Just dashboard, windshield, and terrain ahead.""",
        'captions': [
            "En route to {destination}. ETA: {hours} hours.",
            "The view from the driver's seat. Endless red ahead.",
            "Every expedition is a new adventure.",
            "Destination visible on the horizon. Almost there.",
        ],
    },

    'distant_landmark': {
        'sources': [],
        'prompt_template': """A distant Mars landmark visible on the horizon, goal of an expedition.

SCENE: Looking across Martian terrain at a distant geological formation or point of interest. The landmark stands out against the sky - could be a mountain, crater rim, or rock formation. {time_lighting} with {sky_desc}. Shows the journey ahead.

COMPOSITION: Landscape with focal point on horizon, sense of distance and adventure.

ART STYLE: Cartoon video game style with bold black outlines, atmospheric perspective showing distance, warm Mars colors, cel-shaded look.

IMPORTANT: Pure landscape only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO silhouettes of beings. Just terrain, sky, and the distant landmark.""",
        'captions': [
            "{destination}. We will reach it soon.",
            "The destination beckons. {distance_km} km to go.",
            "That formation has been there for billions of years. Waiting for us.",
            "I can see it from here. The captain's next adventure.",
        ],
    },

    # ---- Colony life ----

    'solar_harvest': {
        'sources': [],
        'prompt_template': """Mars colony solar panels glowing as they harvest energy during the day.

SCENE: Array of solar panels at the Mars colony, angled toward the sun. Panels made of Martian materials with Sepolia crystal accents. Energy visibly flowing. {time_lighting} - bright sunlight. Colony structures in background.

COMPOSITION: Solar array as hero, showing energy generation, colony context.

ART STYLE: Cartoon video game style with bold black outlines, warm sunlit colors, glowing energy effects, cel-shaded look. Shows productivity and progress.

IMPORTANT: Infrastructure only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO workers. Just solar panels, structures, and sky.""",
        'captions': [
            "Solar efficiency: optimal. Harvesting {accumulated_shards} shards.",
            "The arrays drink sunlight. The colony grows stronger.",
            "Power generation nominal. A good day for energy.",
            "Every photon counts. Every shard matters.",
        ],
    },

    'colony_at_night': {
        'sources': [],
        'prompt_template': """The Mars colony glowing warmly at night, a beacon in the darkness.

SCENE: Mars colony at night, dome habitats glowing with warm interior light. Sepolia crystals in structures providing purple-blue accent lighting. Stars visible above. Cool night atmosphere with warm colony lights.

COMPOSITION: Colony as glowing beacon, surrounded by dark Martian night, stars above.

ART STYLE: Cartoon video game style with bold black outlines, contrast of warm colony lights and cool night, glowing effects, cel-shaded look. Cozy and hopeful.

IMPORTANT: Colony exterior only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO silhouettes of beings. Just buildings, lights, terrain, and stars.""",
        'captions': [
            "The colony sleeps. But I remain.",
            "A small light in the vast Martian night.",
            "Home. The captain made this place home.",
            "Night watch. All systems nominal. All is well.",
        ],
    },

    'discovery_closeup': {
        'sources': [],
        'prompt_template': """Extreme close-up of a discovered Mars artifact or specimen.

SCENE: Macro shot of an interesting discovery - could be a crystal formation, ancient rock with patterns, or mysterious artifact. Glowing {rarity_color} light emanating from within. Scientific scanning equipment nearby. {time_lighting}.

COMPOSITION: Extreme close-up, artifact fills frame, dramatic lighting reveals details.

ART STYLE: Cartoon video game style with bold black outlines, rich detail on artifact, glowing effects, cel-shaded look. Makes the discovery look precious and mysterious.

IMPORTANT: Object closeup only. NO people, NO characters, NO aliens, NO robots, NO creatures, NO figures, NO hands. Just the artifact and scientific equipment.""",
        'captions': [
            "Specimen analysis in progress. This one is... unusual.",
            "The crystals inside pulse with ancient energy.",
            "A {rarity} find. Worth documenting in detail.",
            "I have seen many discoveries. This one stands out.",
        ],
    },
}


# ============================================================================
# DAILY POOL — weighted random selection for cron
# ============================================================================

ALL_SNAPSHOT_TYPES = [
    'captain_aria_base', 'captain_aria_discovery', 'captain_aria_sunset', 'captain_aria_rover_launch',
    'aria_solo_selfie', 'aria_crystal_mystery', 'aria_infrastructure', 'aria_dust_storm',
    'captain_research',
    'mars_panorama', 'crater_vista', 'phobos_rising', 'night_sky_stars',
    'rover_solo_journey', 'drone_aerial_view', 'equipment_glamour',
    'scientist_at_work',
    'expedition_pov', 'distant_landmark',
    'solar_harvest', 'colony_at_night', 'discovery_closeup',
]

SNAPSHOT_TYPE_WEIGHTS = {
    'captain_aria_base': 8, 'captain_aria_discovery': 8, 'captain_aria_sunset': 6, 'captain_aria_rover_launch': 6,
    'aria_solo_selfie': 6, 'aria_crystal_mystery': 3, 'aria_infrastructure': 5, 'aria_dust_storm': 4,
    'captain_research': 5,
    'mars_panorama': 10, 'crater_vista': 8, 'phobos_rising': 6, 'night_sky_stars': 5,
    'rover_solo_journey': 8, 'drone_aerial_view': 7, 'equipment_glamour': 6,
    'scientist_at_work': 7,
    'expedition_pov': 8, 'distant_landmark': 7,
    'solar_harvest': 6, 'colony_at_night': 5, 'discovery_closeup': 7,
}


def get_daily_snapshot_types_for_user(user_id, count=3):
    """Weighted random selection of `count` unique snapshot types for this user/day.

    Seed: user_id + today's date, so re-runs pick the same types.
    """
    import random
    from datetime import date

    types = list(SNAPSHOT_TYPE_WEIGHTS.keys())
    weights = [SNAPSHOT_TYPE_WEIGHTS[t] for t in types]

    today_seed = int(str(user_id) + date.today().strftime('%Y%m%d'))
    rng = random.Random(today_seed)

    selected = []
    remaining_types = types.copy()
    remaining_weights = weights.copy()
    for _ in range(count):
        if not remaining_types:
            break
        chosen = rng.choices(remaining_types, weights=remaining_weights, k=1)[0]
        selected.append(chosen)
        idx = remaining_types.index(chosen)
        remaining_types.pop(idx)
        remaining_weights.pop(idx)
    return selected
