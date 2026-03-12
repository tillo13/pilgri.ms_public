#!/usr/bin/env python3
"""
Standalone test script for crew generation using Flux
Only uses utilities.flux_utils - no config dependencies
"""

import utilities.flux_utils as flux_utils
import random
import os

# Standalone test data - no config imports needed
CREW_COLORS = [
    'red', 'blue', 'green', 'purple', 'orange', 'yellow',
    'black', 'white', 'pink', 'cyan', 'magenta', 'gold'
]

CREW_STYLES = [
    'minecraft-style blocky',
    'ghibli-style anime', 
    'claymation clay figure',
    'lego brick construction',
    'pixel art 8-bit',
    'cartoon comic book',
    'fantasy medieval',
    'sci-fi futuristic',
    'steampunk victorian',
    'cyberpunk neon'
]

def get_random_default_leader():
    """Get a random default leader image from static/images/default_leaders/"""
    try:
        default_dir = "static/images/default_leaders"
        
        if not os.path.exists(default_dir):
            print(f"Error: Default leaders directory not found: {default_dir}")
            return None
        
        png_files = [f for f in os.listdir(default_dir) if f.lower().endswith('.png')]
        
        if not png_files:
            print(f"Error: No PNG files found in {default_dir}")
            return None
        
        random_leader = random.choice(png_files)
        print(f"Selected random default leader: {random_leader}")
        
        with open(os.path.join(default_dir, random_leader), 'rb') as f:
            return f.read(), random_leader
            
    except Exception as e:
        print(f"Error selecting random default leader: {e}")
        return None

def test_crew_generation():
    """Test generating a cohesive 4-member crew"""
    
    # Initialize Flux generator
    flux = flux_utils.FluxGenerator()
    
    # Pick random team theme
    team_color = random.choice(CREW_COLORS)
    team_style = random.choice(CREW_STYLES)
    
    crew_results = []
    
    print("=== CREW GENERATION TEST ===")
    print(f"Team Color: {team_color.upper()}")
    print(f"Team Style: {team_style.upper()}")
    print()
    
    # Generate 4 crew members
    for i in range(4):
        member_letter = chr(65 + i)  # A, B, C, D
        print(f"Generating Member {member_letter}...")
        
        try:
            # Get random starting character
            leader_result = get_random_default_leader()
            if not leader_result:
                print(f"✗ Failed Member {member_letter}: Could not get default leader")
                continue
            
            image_data, original_filename = leader_result
            
            # Create team-consistent prompt
            team_prompt = (
                f"convert to {team_style} video game character who is dressed and adorned "
                f"to go on an epic quest, build this character with outfit that is 100% {team_color}, "
                f"adventurous rough explorer gear, bold team uniform appearance, "
                f"style with complete full body and all limbs visible, stylized non-realistic proportions, "
                f"bold outlines, if more than one character select only the most prominent one"
            )
            
            # Transform into crew member
            member_url = flux.process_image(image_data, team_prompt)
            
            crew_results.append({
                'name': f'Member_{member_letter}',
                'original': original_filename,
                'final_styled': member_url,
                'color': team_color,
                'style': team_style,
                'prompt': team_prompt
            })
            
            print(f"✓ Member {member_letter} created: {member_url}")
            
        except Exception as e:
            print(f"✗ Failed Member {member_letter}: {e}")
    
    # Results summary
    print(f"\n=== FINAL CREW ROSTER ===")
    print(f"Team Theme: {team_color.upper()} {team_style.upper()} CREW")
    print("-" * 60)
    
    if crew_results:
        for member in crew_results:
            print(f"{member['name']}: {member['final_styled']}")
            print(f"  Original: {member['original']}")
            print(f"  Style: {member['style']} in {member['color']}")
            print()
    else:
        print("No crew members were successfully generated.")
    
    print(f"Generated {len(crew_results)} out of 4 crew members.")
    return crew_results

if __name__ == "__main__":
    test_crew_generation()