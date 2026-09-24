#!/usr/bin/env python3
"""
Generate 5 Rover Mk II variations with better Kontext prompts.
Tests different prompting approaches to find best style preservation.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator

# The Rover Mk I base image we generated
BASE_IMAGE = "https://storage.googleapis.com/galactica-pilgrim-assets/upgrade_items/vehicles_rover_lv1_1767742582.png"

# 5 different prompts that preserve the original style better
PROMPTS = [
    # Prompt 1: Very explicit preservation
    "Add two more wheels to this rover (making it 6 wheels total) and add a second solar panel on top. Keep the exact same cartoon video game art style, the same grey and white color scheme, the same red Martian terrain background, and the same bold outlines. Only add the extra wheels and panel.",

    # Prompt 2: Minimal change focus
    "Modify this Mars rover to have 6 wheels instead of 4, and add an additional solar panel. Maintain all other aspects exactly: the cartoon style, bold outlines, color palette, terrain, and camera angle.",

    # Prompt 3: Describe what stays the same first
    "Keep this exact rover design, art style, colors, and Martian setting. The only changes: extend the chassis to fit 6 wheels (add 2 middle wheels), and mount a second solar panel beside the first one.",

    # Prompt 4: Upgrade language with preservation
    "Upgrade this rover to Mk II version: add 2 additional wheels in the middle section and a second solar panel. Preserve the cartoon video game aesthetic, bold outlines, grey-white color scheme, and red Mars background exactly as shown.",

    # Prompt 5: Simple and direct
    "Same rover, same style, same colors, same Mars background - but now with 6 wheels and 2 solar panels instead of 4 wheels and 1 panel."
]

def main():
    flux = FluxGenerator()

    print("Generating 5 Rover Mk II variations with better Kontext prompts...")
    print(f"\nBase image: {BASE_IMAGE}\n")

    results = []

    for i, prompt in enumerate(PROMPTS, 1):
        print(f"\n{'='*60}")
        print(f"VARIATION {i}")
        print(f"{'='*60}")
        print(f"Prompt: {prompt}")

        try:
            url = flux.kontext_edit(BASE_IMAGE, prompt, output_format="png")
            print(f"\n✅ Result: {url}")
            results.append((i, url))

        except Exception as e:
            print(f"\n❌ Error: {e}")

    print(f"\n\n{'='*60}")
    print("SUMMARY - All variations:")
    print(f"{'='*60}")
    print(f"\nOriginal Rover Mk I: {BASE_IMAGE}")
    print()
    for i, url in results:
        print(f"Variation {i}: {url}")

if __name__ == '__main__':
    main()
