#!/usr/bin/env python3
"""
Generate ARIA concept art - the colony AI companion.

ARIA is a mysterious AI found on Mars, connected to Sepolia crystals.
She's helpful, curious, and harbors fragmented memories of something ancient.

Usage: python tools/generate_aria_concepts.py
       python tools/generate_aria_concepts.py --round2   # Cute robot variations
"""

import sys
import os
import time
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# Round 1: Original 5 concepts (different styles)
ARIA_CONCEPTS_ROUND1 = {
    'orb_classic': """Stylized comic book illustration, floating luminous orb AI companion,
teal and cyan glowing crystalline sphere with subtle face features visible in the light,
soft ethereal glow emanating outward, Sepolia crystal energy patterns within,
ancient Martian artifact aesthetic, friendly yet mysterious presence,
dark Mars colony background with rust-red hints,
vibrant colors, bold outlines, sci-fi game art style, portrait orientation""",

    'holographic_woman': """Stylized comic book illustration, holographic AI assistant,
translucent teal-glowing female figure made of light and data streams,
geometric patterns flowing through her form like circuitry,
warm friendly expression, slightly ethereal and not quite solid,
hovering above a small Sepolia crystal base that powers her,
dark Mars habitat interior background,
vibrant colors, bold outlines, sci-fi game art style, portrait orientation""",

    'geometric_entity': """Stylized comic book illustration, abstract geometric AI being,
interconnected teal-glowing polyhedrons forming a vaguely humanoid shape,
Sepolia crystal core visible at center pulsing with ancient energy,
floating fragments orbit the main form like data satellites,
mysterious yet approachable presence, alien but not threatening,
Mars dust and red rocks in background,
vibrant colors, bold outlines, sci-fi game art style, portrait orientation""",

    'wall_e_inspired': """Stylized comic book illustration, cute robot AI companion,
small hovering drone-like form with large expressive camera eye,
teal energy glow from Sepolia-powered core, weathered ancient metal casing,
curious tilted head pose, antenna with soft light,
clearly old and found on Mars but still functional and friendly,
Mars colony workshop background with tools and equipment,
vibrant colors, bold outlines, sci-fi game art style, portrait orientation""",

    'spirit_wisp': """Stylized comic book illustration, ethereal energy spirit AI,
flowing wisp-like form of teal and cyan light, vaguely feminine silhouette,
trails of glowing particles like ancient data streams,
gentle glowing eyes that convey warmth and wisdom,
Sepolia crystal shards floating within her translucent form,
hovering in Mars colony corridor with red ambient lighting,
vibrant colors, bold outlines, sci-fi game art style, portrait orientation""",
}

# Round 2: Cute robot variations (user preferred WALL-E style)
ARIA_CONCEPTS_ROUND2 = {
    'walle_rustic': """Stylized comic book illustration, adorable small robot companion,
boxy weathered body with rusty orange-brown patina from centuries on Mars,
large binocular eyes that convey curiosity and warmth,
teal glowing Sepolia crystal visible through chest panel,
small articulated arms, tank treads or hover pads,
dust and sand accumulated in joints showing age,
tilted head pose showing personality,
Mars junkyard background with scattered ancient tech,
vibrant warm colors, bold outlines, Pixar-style charm, portrait orientation""",

    'eve_sleek': """Stylized comic book illustration, elegant hovering robot companion,
smooth white oval body with minimalist design,
single large expressive eye or visor glowing soft teal,
sleek curves, floating gracefully, no visible joints,
subtle teal energy lines tracing the surface like circuitry,
small Sepolia crystal embedded in forehead or chest,
serene helpful expression, advanced but approachable,
clean Mars habitat interior background,
vibrant colors, bold outlines, modern sci-fi aesthetic, portrait orientation""",

    'r2_dome': """Stylized comic book illustration, dome-headed robot companion,
cylindrical body with rounded top, classic astromech proportions,
multiple sensor lights and panels, one main eye lens,
teal and white color scheme with orange accent lights,
Sepolia crystal powering the main processor dome,
small utility arms tucked at sides,
cheerful beeping personality conveyed through pose,
Mars colony hangar background,
vibrant colors, bold outlines, retro sci-fi charm, portrait orientation""",

    'johnny5_expressive': """Stylized comic book illustration, expressive tracked robot companion,
angular head with large camera eyes that convey emotion,
articulated eyebrow plates for expressions,
boxy torso with visible internal components and wires,
teal glowing Sepolia core visible in chest cavity,
long articulated arms with gripper hands,
curious excited pose leaning forward,
old tech aesthetic mixed with alien crystal energy,
Mars research lab background with screens and equipment,
vibrant colors, bold outlines, 80s robot movie charm, portrait orientation""",

    'aria_unique': """Stylized comic book illustration, unique hovering robot companion,
compact spherical core body with extending sensor stalks,
main eye is a large teal-glowing lens with iris-like aperture,
two or three floating satellite orbs connected by energy tethers,
ancient Martian design language - curved, organic metal shapes,
Sepolia crystals integrated throughout like nervous system,
clearly alien origin but friendly demeanor,
mix of weathered ancient and still-functioning,
hovering at eye level, attentive helpful pose,
Mars colony common area background,
vibrant teal and rust colors, bold outlines, game art style, portrait orientation""",
}

# Round 3: WALL-E style with proper game art style (matching shop/discovery items)
ARIA_CONCEPTS_ROUND3 = {
    'aria_boxy_v1': """Cartoon video game item with bold outlines and stylized proportions: adorable small boxy robot companion with large binocular camera eyes, weathered rusty orange-brown metal body from centuries on Mars, teal glowing crystal visible in chest panel, small articulated gripper arms, tank treads, dust accumulated in joints, curious head tilt, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style""",

    'aria_boxy_v2': """Cartoon video game item with bold outlines and stylized proportions: cute compact robot helper with expressive rectangular head, two big round camera lens eyes, small antenna on top, boxy torso with glowing teal Sepolia crystal core, stubby arms with claw hands, hover pad base, friendly curious pose, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style""",

    'aria_tracked_v1': """Cartoon video game item with bold outlines and stylized proportions: friendly tracked robot companion with rounded boxy body, single large expressive camera eye with teal glow, small manipulator arms, chunky tank treads, weathered orange-rust patina, glowing Sepolia crystal heart visible through worn chest panel, helpful attentive pose, isolated on red Martian terrain, vibrant colors with reds and oranges, video game asset style""",

    'aria_hover_v1': """Cartoon video game item with bold outlines and stylized proportions: small hovering robot assistant with spherical head featuring big friendly camera eye, compact cylindrical body with glowing teal Sepolia energy core, tiny articulated arms, anti-gravity hover ring at base, weathered ancient metal with rust spots, eager helpful pose floating at eye level, isolated on red Martian terrain, vibrant Mars color palette, video game asset style""",

    'aria_dome_v1': """Cartoon video game item with bold outlines and stylized proportions: cute dome-headed robot companion with transparent teal-glowing brain dome containing Sepolia crystal, friendly face plate with two expressive eye sensors, compact boxy body, small utility arms, sturdy wheel base, ancient weathered metal texture, curious tilted head pose, isolated on red Martian terrain, vibrant colors with reds and oranges, video game asset style""",
}

# Round 4: Ancient faceless robot - weathered, foreign, mysterious but functional
ARIA_CONCEPTS_ROUND4 = {
    'aria_ancient_v1': """Cartoon video game item with bold outlines and stylized proportions: ancient faceless robot probe, no face just a single dim sensor lens, heavily weathered bronze and rust metal body pitted from millennia on Mars, strange curved alien design language unlike human tech, faint teal glow from cracks where energy seeps through, chunky treads half-buried in dust, antenna broken and bent, mysterious and foreign but still operational, isolated on red Martian terrain, vibrant colors with reds and oranges, video game asset style""",

    'aria_ancient_v2': """Cartoon video game item with bold outlines and stylized proportions: mysterious ancient robot artifact, faceless ovoid head with single dark sensor slit, body covered in faded alien glyphs and symbols, extremely weathered metal with layers of rust and dust accumulation, subtle teal energy pulsing through worn seams, stubby manipulator arms showing age, hover mechanism sputtering but working, clearly thousands of years old but functional, isolated on red Martian terrain, vibrant Mars colors, video game asset style""",

    'aria_ancient_v3': """Cartoon video game item with bold outlines and stylized proportions: primordial robot sentinel, no face just worn sensor array, squat cylindrical body of pockmarked ancient metal, strange non-human proportions and curves, Mars dust permanently fused to surface, faint teal crystalline veins visible through corroded panels, heavy duty tracks worn smooth from ages, alien and foreign yet somehow approachable, isolated on red Martian terrain, vibrant colors with reds and oranges, video game asset style""",

    'aria_ancient_v4': """Cartoon video game item with bold outlines and stylized proportions: enigmatic ancient Mars robot, featureless dome head with single recessed lens, rounded body shape unlike any Earth design, surface texture of eroded metal with centuries of patina, barely visible teal glow deep within chassis, small folded utility limbs, anti-gravity base flickering weakly, looks like it predates human civilization, isolated on red Martian terrain, vibrant Mars color palette, video game asset style""",

    'aria_ancient_v5': """Cartoon video game item with bold outlines and stylized proportions: forgotten robot relic from ancient Mars, no eyes just dark sensor strip across featureless head, compact angular body with alien geometric patterns worn almost smooth, extreme weathering with rust streaks and dust deposits, hints of teal energy glowing from deep crevices, sturdy wheel base crusted with red soil, clearly functional despite immense age, mysterious origin, isolated on red Martian terrain, vibrant colors, video game asset style""",
}

# Round 5: Refined based on user preferences
# Pattern: compact, ground-based (wheels/treads), single sensor strip (no eyes),
# angular/boxy body, heavy weathering, subtle teal in crevices only,
# alien geometric patterns, functional but ancient
ARIA_CONCEPTS_ROUND5 = {
    'aria_refined_v1': """Cartoon video game item with bold outlines and stylized proportions: small angular robot relic, no face just horizontal dark sensor slit across flat head plate, compact boxy chassis with alien geometric panel lines worn smooth from ages, chunky tank treads caked with Mars dust, extreme rust and weathering patina, faint teal glow visible only deep in panel seams, stubby utility arms folded at sides, ancient alien design clearly not human technology, isolated on red Martian terrain, vibrant colors with reds and oranges, video game asset style""",

    'aria_refined_v2': """Cartoon video game item with bold outlines and stylized proportions: compact wheeled robot artifact, featureless angular head with single thin dark visor strip, squared-off body covered in eroded alien geometric grooves, four sturdy wheels half-buried in red soil, heavily weathered bronze-rust metal surface, subtle teal energy barely visible through worn cracks, small folded manipulator limbs, looks like ancient alien surveyor machine, isolated on red Martian terrain, vibrant Mars colors, video game asset style""",

    'aria_refined_v3': """Cartoon video game item with bold outlines and stylized proportions: boxy ancient probe robot, flat faceless head with recessed dark sensor band, angular torso with faded alien circuit patterns etched into metal, heavy duty tracked base encrusted with centuries of dust, extreme weathering with rust streaks and pitting, dim teal glow seeping from deep joints, compact functional shape unlike any Earth robot, mysterious origin, isolated on red Martian terrain, vibrant colors with reds and oranges, video game asset style""",

    'aria_refined_v4': """Cartoon video game item with bold outlines and stylized proportions: squat angular sentinel robot, no eyes just dark horizontal sensor slot in blocky head, compact cubic body with geometric alien markings almost worn away, wide stable wheel base crusted red with Mars soil, extreme age showing in every corroded surface, hints of teal light from internal crevices, retracted tool arms showing wear, clearly predates humanity, isolated on red Martian terrain, vibrant Mars color palette, video game asset style""",

    'aria_refined_v5': """Cartoon video game item with bold outlines and stylized proportions: small tracked reconnaissance robot from ancient Mars, faceless wedge-shaped head with thin dark sensor strip, angular armored body with alien geometric panel seams, rugged caterpillar treads worn smooth from millennia, heavy rust patina and dust accumulation everywhere, barely visible teal energy in deepest cracks, compact utility form clearly still operational, alien technology of unknown origin, isolated on red Martian terrain, vibrant colors, video game asset style""",
}

# Round 6: Same form as V3 but FRIENDLY not evil
# Boxy tracked faceless sensor-band robot, but with:
# - Softer rounded edges, warm rust tones
# - Smaller/cuter proportions, friendly helper vibe
# - Sensor strip reads as curious/observing not targeting
# - Utility robot not war machine
ARIA_CONCEPTS_ROUND6 = {
    'aria_friendly_v1': """Cartoon video game item with bold outlines and stylized proportions: small friendly ancient robot helper, rounded boxy body with soft edges, flat head with gentle curved sensor band across front, warm orange-rust weathered metal with friendly worn patina, compact chunky treads, slightly tilted head pose suggesting curiosity, faded geometric patterns on panels, subtle teal glow in seams, cute utility robot proportions not threatening, ancient but approachable, isolated on red Martian terrain, warm vibrant colors with oranges and reds, video game asset style""",

    'aria_friendly_v2': """Cartoon video game item with bold outlines and stylized proportions: adorable weathered robot relic, compact cube-shaped body with rounded corners, small flat head with thin dark observation strip, warm bronze and orange rust patina from ages on Mars, stubby friendly treads, short folded helper arms at sides, geometric alien markings worn soft, hint of teal light deep inside, looks like ancient helpful assistant not weapon, curious attentive pose, isolated on red Martian terrain, warm vibrant Mars colors, video game asset style""",

    'aria_friendly_v3': """Cartoon video game item with bold outlines and stylized proportions: cute ancient surveyor bot, boxy but with softened rounded edges, flat faceless head with gentle recessed sensor band, heavily weathered warm rust and tan metal surface, small tracked base caked with friendly red dust, compact helpful proportions like a toolbox on treads, faded alien circuit patterns, barely visible teal energy in cracks, feels old and wise not menacing, isolated on red Martian terrain, warm oranges and reds, video game asset style""",

    'aria_friendly_v4': """Cartoon video game item with bold outlines and stylized proportions: small endearing robot artifact from ancient Mars, rounded rectangular body with worn smooth edges, flat top with subtle curved visor strip, warm golden-rust weathered patina everywhere, chunky little wheels crusted with red soil, folded utility appendages tucked at sides, geometric alien designs faded with age, soft teal glow from deep within, curious head tilt, friendly helper vibe despite immense age, isolated on red Martian terrain, warm vibrant colors, video game asset style""",

    'aria_friendly_v5': """Cartoon video game item with bold outlines and stylized proportions: loveable ancient robot companion, compact boxy shape with all edges softened by erosion, flat featureless head with gentle dark sensor strip, beautiful warm copper-rust weathering from millennia, small sturdy treads worn smooth, diminutive size feels approachable, alien geometric patterns almost polished away, hint of teal energy seeping from joints, feels like a curious old friend not a threat, isolated on red Martian terrain, warm orange and rust tones, video game asset style""",
}

# Round 7: Friendly ancient robot WITH mysterious Martian hieroglyphs
# Same friendly form but covered in unreadable ancient alien symbols
# The markings connect to deeper mysteries - The Signal, Sepolia origins
ARIA_CONCEPTS_ROUND7 = {
    'aria_glyphs_v1': """Cartoon video game item with bold outlines and stylized proportions: friendly ancient robot covered in mysterious alien hieroglyphs, compact boxy body with soft rounded edges, flat faceless head with gentle sensor strip, warm copper-rust weathered surface, body panels covered in faded unreadable Martian symbols and geometric glyphs, strange circular and angular markings etched into metal, some symbols faintly glowing teal, small treads crusted with red dust, curious helpful pose, ancient mystery machine, isolated on red Martian terrain, warm vibrant colors, video game asset style""",

    'aria_glyphs_v2': """Cartoon video game item with bold outlines and stylized proportions: adorable weathered robot artifact with alien inscriptions, rounded boxy shape with soft edges, dark sensor band across flat head, warm bronze-rust patina, entire body etched with intricate Martian hieroglyphics and strange symbols nobody can read, geometric patterns mixed with curved alien writing, some markings pulse faintly teal, chunky friendly treads, feels like ancient helpful relic with secrets, isolated on red Martian terrain, warm orange tones, video game asset style""",

    'aria_glyphs_v3': """Cartoon video game item with bold outlines and stylized proportions: cute ancient surveyor bot covered in mysterious markings, boxy body softened by millennia of erosion, faceless head with gentle visor strip, heavily weathered warm rust surface inscribed with unreadable alien glyphs, spiral symbols and angular Martian writing covering panels, occasional teal glow from within symbol grooves, small tracked base, curious tilted pose, ancient secrets encoded in its surface, isolated on red Martian terrain, warm colors, video game asset style""",

    'aria_glyphs_v4': """Cartoon video game item with bold outlines and stylized proportions: small friendly robot relic with hieroglyphic engravings, compact rounded-corner cube body, flat top with subtle dark sensor band, warm golden-rust weathering, panels covered in faded alien pictographs and geometric inscriptions, strange Martian symbols that seem almost like a language, hints of teal energy tracing some glyphs, stubby wheels with red dust, approachable ancient helper carrying unknown messages, isolated on red Martian terrain, warm vibrant tones, video game asset style""",

    'aria_glyphs_v5': """Cartoon video game item with bold outlines and stylized proportions: endearing ancient robot companion inscribed with alien mystery, compact boxy form with erosion-softened edges, gentle dark sensor strip on faceless head, beautiful copper-rust patina, entire surface decorated with intricate unreadable Martian hieroglyphs and sacred geometric patterns, symbols worn but visible, faint teal glow emanating from deepest carvings, small sturdy treads, feels like it holds ancient secrets in its markings, isolated on red Martian terrain, warm orange and rust colors, video game asset style""",
}

# Round 8: Final refinement based on user feedback
# - Compact boxy with soft erosion edges (from friendly_v5)
# - Small sturdy treads, warm copper-rust
# - ADD utility arms/hands for helper function
# - NO screen or visor - too human/Earth-tech
# - ALIEN sensor - recessed nodes, crystalline slit, organic shapes
# - SUBTLE hieroglyphs - just 2-3 mysterious markings max
# - Foreign proportions and materials that feel grown not manufactured
ARIA_CONCEPTS_ROUND8 = {
    'aria_final_v1': """Cartoon video game item with bold outlines and stylized proportions: loveable ancient alien robot helper, compact boxy body with erosion-softened edges, small articulated manipulator arms with three-fingered grippers, no screen or visor just a row of tiny recessed sensor nodes across flat head, warm copper-rust weathered patina, organic curves mixed with geometric panels, just two or three faded alien symbols etched into shoulder, small sturdy treads, hint of teal glow from sensor nodes, foreign design clearly not human technology, isolated on red Martian terrain, warm orange and rust colors, video game asset style""",

    'aria_final_v2': """Cartoon video game item with bold outlines and stylized proportions: endearing ancient utility bot, rounded boxy form softened by millennia, stubby functional arms with claw grippers folded at sides, no eyes just a thin crystalline slit sensor that glows faint teal, warm bronze-rust surface with beautiful patina, strange organic-geometric hybrid design, only two subtle alien glyphs near base, chunky friendly treads crusted with dust, proportions slightly off in charming alien way, feels grown not manufactured, isolated on red Martian terrain, warm vibrant colors, video game asset style""",

    'aria_final_v3': """Cartoon video game item with bold outlines and stylized proportions: cute ancient robot companion with helper arms, compact cube-like body with soft worn edges, small utility arms with pincer hands, no screen just three dim recessed sensor pits in faceless head plate, warm copper and rust weathering from ages, alien curves that feel organic not mechanical, one mysterious spiral glyph on chest panel, small tracked base with red dust, faint teal energy in sensor recesses, foreign ancient technology, isolated on red Martian terrain, warm orange tones, video game asset style""",

    'aria_final_v4': """Cartoon video game item with bold outlines and stylized proportions: friendly alien robot artifact with manipulators, boxy body eroded smooth by time, articulated helper arms tucked at sides with odd three-digit hands, no visor just a horizontal row of tiny crystalline sensor bumps, warm golden-rust patina everywhere, design feels grown from metal not built, two small hieroglyphic marks near shoulder joint, sturdy little wheels with dust crust, barely visible teal glow from crystal sensors, clearly not from Earth, isolated on red Martian terrain, warm rust colors, video game asset style""",

    'aria_final_v5': """Cartoon video game item with bold outlines and stylized proportions: adorable ancient helper robot, compact rounded-box shape worn smooth, small functional grabber arms with alien joint design, no screen or camera just a subtle recessed sensor groove across head, beautiful warm copper-rust surface aged for millennia, organic flowing lines mixed with geometric, single mysterious alien symbol on one panel, chunky friendly treads, hint of teal in sensor groove, proportions charmingly foreign not human-made, isolated on red Martian terrain, warm orange and copper tones, video game asset style""",
}

# Round 9: Truly alien - asymmetric, rock-fused, non-bilateral
# Attention/presence comes from glowing Sepolia crystal core, not eyes
# Made FOR Mars terrain - tracks, rock-like material
# Maybe 3 limbs, radial design, or asymmetric
# The crystal pulses brighter when focused on you = "seeing"
ARIA_CONCEPTS_ROUND9 = {
    'aria_alien_v1': """Cartoon video game item with bold outlines and stylized proportions: truly alien ancient robot made of fused Martian rock and metal, asymmetric body with three stubby manipulator limbs arranged radially, no face or eyes just a glowing teal Sepolia crystal core visible through eroded chest cavity, body texture like weathered red sandstone fused with bronze, heavy triangular track base designed for Mars terrain, the crystal pulses with inner light suggesting awareness, completely non-human design language, one faded alien glyph on side, isolated on red Martian terrain, warm rust and teal colors, video game asset style""",

    'aria_alien_v2': """Cartoon video game item with bold outlines and stylized proportions: ancient Martian-native robot entity, rounded asymmetric form that looks grown from red rock, single large manipulator arm and two smaller tool appendages, no eyes but a crystalline Sepolia node embedded in top that glows teal when attentive, surface is weathered sandstone-metal hybrid material, wide stable treads fused with rocky base, presence conveyed through crystal glow not facial features, radial symmetry elements, two subtle alien markings, isolated on red Martian terrain, warm orange and copper tones, video game asset style""",

    'aria_alien_v3': """Cartoon video game item with bold outlines and stylized proportions: primordial robot being fused with Mars itself, compact body of eroded red rock and ancient bronze, three short arms with odd crystalline grabbers arranged in triangle, no face just a recessed cavity where teal Sepolia crystal heart glows brighter when focused, looks like it grew from the planet, chunky asymmetric treads worn smooth, completely alien proportions yet somehow friendly, single spiral glyph on one arm, crystal provides sense of awareness without eyes, isolated on red Martian terrain, warm rust colors, video game asset style""",

    'aria_alien_v4': """Cartoon video game item with bold outlines and stylized proportions: ancient alien helper made of Martian materials, egg-shaped asymmetric body of fused sandstone and weathered metal, two manipulator limbs on one side and one stabilizer on other, glowing teal Sepolia crystal cluster where a face would be that pulses to show attention, built for Mars terrain with wide rocky treads, texture like red desert rock polished by wind, non-bilateral design feels foreign but approachable, two small alien symbols near crystal, warm copper-rust surface, isolated on red Martian terrain, video game asset style""",

    'aria_alien_v5': """Cartoon video game item with bold outlines and stylized proportions: truly foreign ancient robot companion, compact asymmetric form of red Martian rock fused with bronze, radial arrangement of three small utility limbs, no eyes or face just a prominent teal Sepolia crystal orb in center that glows warmly when attentive, the crystal IS how it sees and connects, body weathered by millennia of Mars winds, stable triangular tread base made for rocky terrain, one mysterious alien glyph, feels alive through crystal presence not facial features, isolated on red Martian terrain, warm orange and teal, video game asset style""",
}

# Round 10: Based on aria_alien_v3 but refined
# - Keep: crab-like rocky body, crystalline teal hands, compact chunky form
# - Change: legs to tracks, heart to organic Sepolia crystal cluster/aura
# - Add: subtle feminine touches, better glyphs (2-3), softer curves
ARIA_CONCEPTS_ROUND10 = {
    'aria_crab_v1': """Cartoon video game item with bold outlines and stylized proportions: feminine ancient rock golem robot, compact body of weathered red Martian stone with softer rounded curves, two crystalline teal grabber arms with elegant claw hands, no face just an organic glowing Sepolia crystal cluster in chest that pulses with blue-teal aura, heavy tracked base instead of legs for Mars terrain, subtle spiral alien glyph on one shoulder and angular symbol on hip, texture like eroded sandstone, slightly smaller proportions feel graceful not brutish, ancient and mysterious, isolated on red Martian terrain, warm rust and teal colors, video game asset style""",

    'aria_crab_v2': """Cartoon video game item with bold outlines and stylized proportions: elegant rock creature robot with feminine grace, body of fused red Mars stone with smooth erosion-worn curves, two teal crystalline manipulator arms ending in delicate crystal claws, central Sepolia crystal formation glowing with soft blue-teal energy aura instead of heart shape, wide stable caterpillar tracks for rocky terrain, two mysterious alien hieroglyphs etched into stone shoulder plates, faceless but presence conveyed through crystal glow, compact and charming proportions, isolated on red Martian terrain, warm orange and teal, video game asset style""",

    'aria_crab_v3': """Cartoon video game item with bold outlines and stylized proportions: graceful ancient Mars golem, feminine curved body of weathered red sandstone and bronze, elegant teal crystal arms with three-fingered crystalline hands, no eyes just a beautiful irregular Sepolia crystal cluster embedded in torso that emanates soft teal light, chunky triangular track base built for Mars rocks, three subtle alien symbols placed on shoulder chest and base, body texture like wind-polished desert stone, smaller refined proportions feel ancient yet approachable, isolated on red Martian terrain, warm rust and vibrant teal, video game asset style""",

    'aria_crab_v4': """Cartoon video game item with bold outlines and stylized proportions: petite rock guardian robot with feminine form, compact body of eroded Martian red rock with gentle rounded shapes, two graceful crystalline teal arms with elegant grabber claws, organic Sepolia crystal formation in chest glowing with dreamy blue-teal aura light, sturdy tank treads instead of legs, spiral glyph on one arm and geometric alien symbol on torso, faceless but crystal provides warm attentive presence, texture like ancient weathered stone, charming proportions not intimidating, isolated on red Martian terrain, warm copper and teal colors, video game asset style""",

    'aria_crab_v5': """Cartoon video game item with bold outlines and stylized proportions: delicate ancient stone robot with feminine grace, body of red Martian rock fused with bronze showing soft curves and erosion, two teal crystalline manipulator arms with pretty crystal claw hands, irregular glowing Sepolia crystal cluster where heart would be pulsing soft blue-teal energy, wide stable tracked base for Mars terrain, two or three mysterious alien hieroglyphs placed tastefully on shoulders and hip, no face but crystal glow conveys gentle awareness, compact elegant proportions feel ancient friend not threat, isolated on red Martian terrain, warm rust orange and teal, video game asset style""",
}

# Round 11: Welcoming guide bot - SOFT and APPROACHABLE
# - Egg/oval rocky body with soft curves (no sharp edges)
# - Rounded hands like mittens/pads (NO claws)
# - Sepolia crystals emerging subtly from shoulders/back/joints (not as head)
# - Small sensor strip for awareness
# - Friendly welcoming proportions - she's a guide!
ARIA_CONCEPTS_ROUND11 = {
    'aria_guide_v1': """Cartoon video game item with bold outlines and stylized proportions: welcoming ancient rock guide robot, soft egg-shaped body of weathered red Martian stone with completely rounded curves no sharp edges, two gentle arms ending in soft rounded mitten-like hands, small teal Sepolia crystals growing naturally from shoulder joints and back like a succulent, subtle dark sensor strip across upper body for awareness, wide friendly tracked base for Mars terrain, two small alien glyphs on hip, texture like smooth river stone, compact cute proportions feel like a helpful friend, isolated on red Martian terrain, warm rust and soft teal accents, video game asset style""",

    'aria_guide_v2': """Cartoon video game item with bold outlines and stylized proportions: friendly ancient Martian guide bot, rounded oval body of fused red Mars rock with soft pillowy curves, two stubby arms with padded rounded grabber hands like oven mitts, small glowing teal Sepolia crystal clusters emerging from shoulder blades and one hip joint, gentle recessed sensor band across chest area, chunky welcoming caterpillar tracks, body texture like wind-polished sandstone, one spiral glyph on arm, approachable proportions like a helpful companion not a warrior, isolated on red Martian terrain, warm orange and subtle teal, video game asset style""",

    'aria_guide_v3': """Cartoon video game item with bold outlines and stylized proportions: adorable ancient stone helper bot, soft rounded egg body of eroded Martian red rock with no sharp angles anywhere, two chubby arms with soft padded circular hands perfect for gentle gestures, tiny teal Sepolia crystal formations sprouting from back and one shoulder like moss, small curved sensor groove across upper torso, friendly wide tank treads, two weathered alien symbols on side, body smooth like tumbled beach stone, small welcoming proportions perfect for a guide companion, isolated on red Martian terrain, warm copper-rust and gentle teal highlights, video game asset style""",

    'aria_guide_v4': """Cartoon video game item with bold outlines and stylized proportions: cuddly ancient Martian companion bot, plump oval body of soft weathered red Mars stone with pillowy rounded shape, two short arms ending in soft bulbous grabber pads like cartoon mittens, delicate teal Sepolia crystals naturally emerging from shoulder joint and lower back, subtle recessed sensor dimple on front, wide stable friendly tracks, single mysterious glyph on hip, texture like worn desert pebble, compact huggable proportions make perfect welcoming guide, isolated on red Martian terrain, warm orange and soft teal accents, video game asset style""",

    'aria_guide_v5': """Cartoon video game item with bold outlines and stylized proportions: sweet ancient rock guide companion, smooth egg-shaped body of fused red Martian stone with completely soft rounded form no edges, two gentle arms with rounded paddle-like hands, small glowing teal Sepolia crystals growing organically from shoulders and back ridge like tiny succulents, thin curved sensor line across body, chunky welcoming caterpillar treads, two or three faded alien glyphs placed on arm and hip, surface like polished river rock, friendly small proportions feel safe and helpful, isolated on red Martian terrain, warm rust and subtle blue-teal crystal glow, video game asset style""",
}

# Round 12: Refined from guide_v1 based on feedback
# - Less egg-like, more angular rock pieces fitted together
# - Smaller eyes/sensor area - more subtle
# - ALL rock material (metal wouldn't survive Mars)
# - PURPLE Sepolia crystals with orange inner glow (matching shard icon style)
# - Add 2-3 alien glyphs
# - Keep: warm rust color, tracks, rounded mitten hands
ARIA_CONCEPTS_ROUND12 = {
    'aria_rock_v1': """Cartoon video game item with bold outlines and stylized proportions: ancient Martian rock golem guide, body made of fitted angular red Mars stone pieces like puzzle pieces joined together not egg shaped, two arms of jointed rock segments ending in soft rounded stone mitten hands, small subtle dark sensor groove recessed into head area, glowing purple Sepolia crystal shards with orange inner energy emerging naturally from shoulder joint and back, chunky stone caterpillar tracks, two mysterious alien glyphs carved into side, entire body weathered red sandstone texture no metal parts, friendly compact proportions, isolated on red Martian terrain, warm rust orange and purple crystal glow, video game asset style""",

    'aria_rock_v2': """Cartoon video game item with bold outlines and stylized proportions: welcoming stone companion robot made entirely of Mars rock, angular body of interlocking weathered red stone segments fitted together like ancient masonry, two chunky rock arms with soft rounded grabber pads at ends, tiny recessed sensor dimple barely visible on front, purple crystalline Sepolia shards with warm orange glow growing from shoulder and hip joints, wide stable stone treads, three faded alien hieroglyphs etched into rock surface, texture of wind-eroded sandstone throughout, approachable helper proportions, isolated on red Martian terrain, warm copper-rust and purple-orange crystal accents, video game asset style""",

    'aria_rock_v3': """Cartoon video game item with bold outlines and stylized proportions: adorable ancient rock guide made of Martian stone only, compact body of multiple angular red rock pieces fused and fitted together organically, jointed stone arms ending in rounded puffy stone mittens, small subtle sensor line carved into upper body, beautiful purple Sepolia crystals with orange inner fire sprouting from back ridge and one shoulder, chunky rocky caterpillar treads, two alien symbols weathered into stone hip and arm, every part looks like carved eroded Mars sandstone no metal anywhere, cute welcoming proportions, isolated on red Martian terrain, warm rust and glowing purple-orange crystals, video game asset style""",

    'aria_rock_v4': """Cartoon video game item with bold outlines and stylized proportions: friendly Martian stone golem companion, body built from angular fitted red rock segments pieced together like natural formation, two stone limb arms with soft rounded rock paddle hands, barely visible dark sensor groove in faceless head region, purple Sepolia crystal clusters with orange energy glow emerging from shoulder blade area and lower back, sturdy stone tank treads, three mysterious glyphs carved shallow into weathered surface, entirely made of eroded red Mars sandstone material, small compact friendly proportions perfect for guide, isolated on red Martian terrain, warm orange-rust and purple crystal glow, video game asset style""",

    'aria_rock_v5': """Cartoon video game item with bold outlines and stylized proportions: sweet ancient guide golem of pure Martian rock, body assembled from fitted angular red stone pieces like geological puzzle, two rock segment arms ending in soft bulbous stone grabber mitts, tiny subtle recessed sensor area on upper body, gorgeous purple Sepolia shards with fiery orange inner glow growing organically from shoulders and back, wide chunky stone caterpillar base, two or three alien hieroglyphs etched faintly into side, texture entirely wind-polished red sandstone no metal components, compact adorable proportions feel safe and helpful, isolated on red Martian terrain, warm rust and vibrant purple-orange crystal accents, video game asset style""",
}


def generate_concept(flux, name, prompt):
    """Generate a single ARIA concept and upload to GCS"""
    print(f"\n{'='*60}")
    print(f"Generating ARIA concept: {name}")
    print(f"{'='*60}")

    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={
            'prompt': prompt,
            'aspect_ratio': '3:4',  # Portrait for character art
        }
    )

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    print(f"Replicate URL: {replicate_url[:80]}...")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"aria/concept_{name}_{timestamp}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    print(f"GCS URL: {gcs_url}")
    return gcs_url


def main():
    parser = argparse.ArgumentParser(description='Generate ARIA concept art')
    parser.add_argument('--round2', action='store_true',
                        help='Generate round 2: cute robot variations')
    parser.add_argument('--round3', action='store_true',
                        help='Generate round 3: game art style (matching shop items)')
    parser.add_argument('--round4', action='store_true',
                        help='Generate round 4: ancient faceless weathered robot')
    parser.add_argument('--round5', action='store_true',
                        help='Generate round 5: refined angular sensor-strip design')
    parser.add_argument('--round6', action='store_true',
                        help='Generate round 6: friendly not evil versions')
    parser.add_argument('--round7', action='store_true',
                        help='Generate round 7: friendly with alien hieroglyphs')
    parser.add_argument('--round8', action='store_true',
                        help='Generate round 8: final refinement with arms, alien sensor, subtle glyphs')
    parser.add_argument('--round9', action='store_true',
                        help='Generate round 9: truly alien - asymmetric, rock-fused, crystal-core presence')
    parser.add_argument('--round10', action='store_true',
                        help='Generate round 10: crab-like rocky form with tracks, crystal cluster, feminine touches')
    parser.add_argument('--round11', action='store_true',
                        help='Generate round 11: welcoming guide bot - soft, rounded, approachable')
    parser.add_argument('--round12', action='store_true',
                        help='Generate round 12: angular rock pieces, purple crystals, smaller eyes, glyphs')
    args = parser.parse_args()

    if args.round12:
        concepts = ARIA_CONCEPTS_ROUND12
        round_name = "Round 12: Rock Golem (Angular Pieces, Purple Crystals, Glyphs)"
    elif args.round11:
        concepts = ARIA_CONCEPTS_ROUND11
        round_name = "Round 11: Welcoming Guide Bot (Soft, Rounded, Approachable)"
    elif args.round10:
        concepts = ARIA_CONCEPTS_ROUND10
        round_name = "Round 10: Crab-Like Rocky Form (Tracks, Crystal Cluster, Feminine)"
    elif args.round9:
        concepts = ARIA_CONCEPTS_ROUND9
        round_name = "Round 9: Truly Alien (Asymmetric, Rock-Fused, Crystal Core = Presence)"
    elif args.round8:
        concepts = ARIA_CONCEPTS_ROUND8
        round_name = "Round 8: Final (Arms, Alien Sensor, Subtle Glyphs)"
    elif args.round7:
        concepts = ARIA_CONCEPTS_ROUND7
        round_name = "Round 7: Friendly Ancient Robot with Martian Hieroglyphs"
    elif args.round6:
        concepts = ARIA_CONCEPTS_ROUND6
        round_name = "Round 6: Friendly Ancient Robot (Soft Edges, Warm Tones)"
    elif args.round5:
        concepts = ARIA_CONCEPTS_ROUND5
        round_name = "Round 5: Refined (Angular, Sensor Strip, Wheeled/Tracked, Ancient)"
    elif args.round4:
        concepts = ARIA_CONCEPTS_ROUND4
        round_name = "Round 4: Ancient Faceless Weathered Robot"
    elif args.round3:
        concepts = ARIA_CONCEPTS_ROUND3
        round_name = "Round 3: Game Art Style (WALL-E + Shop Item Style)"
    elif args.round2:
        concepts = ARIA_CONCEPTS_ROUND2
        round_name = "Round 2: Cute Robot Variations"
    else:
        concepts = ARIA_CONCEPTS_ROUND1
        round_name = "Round 1: Style Exploration"

    print("=" * 60)
    print(f"ARIA Concept Art Generator - {round_name}")
    print("=" * 60)
    print(f"\nGenerating {len(concepts)} visual concepts for ARIA...")
    print("Style: Comic book / stylized game art\n")

    flux = FluxGenerator()

    results = {}
    for name, prompt in concepts.items():
        try:
            url = generate_concept(flux, name, prompt)
            results[name] = url
            time.sleep(2)  # Rate limiting
        except Exception as e:
            print(f"Error generating {name}: {e}")
            results[name] = None

    print("\n" + "=" * 60)
    print("ARIA CONCEPT ART COMPLETE")
    print("=" * 60)

    for name, url in results.items():
        status = "✓" if url else "✗"
        print(f"  {status} {name}: {url or 'FAILED'}")

    return results


if __name__ == '__main__':
    main()
