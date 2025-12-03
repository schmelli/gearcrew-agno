#!/usr/bin/env python3
"""Import glossary terms from JSON into GearGraph.

Usage:
    uv run python scripts/import_glossary.py glossary.json
    uv run python scripts/import_glossary.py  # Uses inline data
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.db.memgraph import import_glossary_terms, get_all_glossary_terms


def normalize_term(term: dict) -> dict:
    """Normalize term dict to match expected format."""
    return {
        "name": term.get("name", ""),
        "definition": term.get("Definition") or term.get("definition", ""),
        "category": term.get("category", ""),
        "aliases": term.get("aliases", []),
    }


def import_from_json(json_data: list[dict]) -> dict:
    """Import glossary terms from JSON data."""
    # Normalize the terms (handle "Definition" vs "definition" key)
    normalized = [normalize_term(t) for t in json_data]

    # Filter out invalid entries
    valid_terms = [t for t in normalized if t["name"] and t["definition"]]

    print(f"Found {len(valid_terms)} valid terms to import")

    # Import using existing function
    stats = import_glossary_terms(valid_terms)

    return stats


def main():
    # Check for file argument
    if len(sys.argv) > 1:
        json_file = Path(sys.argv[1])
        if not json_file.exists():
            print(f"Error: File not found: {json_file}")
            sys.exit(1)

        with open(json_file) as f:
            data = json.load(f)
    else:
        # Use the inline glossary data
        data = GLOSSARY_DATA

    print(f"Importing {len(data)} glossary terms...")
    stats = import_from_json(data)

    print(f"\nImport complete!")
    print(f"  Created: {stats.get('created', 0)}")
    print(f"  Updated: {stats.get('updated', 0)}")
    print(f"  Failed:  {stats.get('failed', 0)}")

    # Show current count
    all_terms = get_all_glossary_terms()
    print(f"\nTotal glossary terms in database: {len(all_terms)}")


# Inline glossary data for direct import
GLOSSARY_DATA = [
  {
    "name": "Denier",
    "Definition": "A unit of measurement that determines the fiber thickness of individual threads or filaments used in textiles, defined as the mass in grams of 9,000 meters of the fiber. It serves as a primary indicator of a fabric's weight and potential durability.",
    "category": "Material Science",
    "aliases": [
      "D",
      "Linear Mass Density"
    ]
  },
  {
    "name": "Ripstop",
    "Definition": "A fabric weaving technique where a thicker, stronger reinforcement yarn is interwoven at regular intervals in a crosshatch or grid pattern to mechanically contain punctures and prevent tears from propagating.",
    "category": "Fabric Construction",
    "aliases": [
      "Reinforced Weave",
      "Grid Weave"
    ]
  },
  {
    "name": "Silnylon",
    "Definition": "A synthetic fabric created by impregnating nylon fibers with liquid silicone, which significantly increases tear strength but leaves the fabric hydrophilic, causing it to absorb water and sag when wet.",
    "category": "Shelter Fabrics",
    "aliases": [
      "Sil-Nylon",
      "Silicone-Impregnated Nylon",
      "Silicone Nylon"
    ]
  },
  {
    "name": "Silpoly",
    "Definition": "A polyester fabric coated or impregnated with silicone. Unlike nylon, it is hydrophobic and does not absorb water or sag when wet, and it offers superior UV resistance compared to nylon.",
    "category": "Shelter Fabrics",
    "aliases": [
      "Sil-Poly",
      "Silicone-Coated Polyester",
      "Silicone Polyester"
    ]
  },
  {
    "name": "Dyneema Composite Fabric",
    "Definition": "A non-woven laminate fabric consisting of a grid of Ultra-High Molecular Weight Polyethylene (UHMWPE) fibers sandwiched between two layers of polyester film. It is waterproof, has zero stretch, and offers an extremely high strength-to-weight ratio.",
    "category": "High-Performance Textiles",
    "aliases": [
      "DCF",
      "Cuben Fiber",
      "CTF3",
      "Non-Woven Dyneema"
    ]
  },
  {
    "name": "Kerlon",
    "Definition": "A proprietary silicone-coated nylon fabric developed by Hilleberg featuring a triple-coating of 100% silicone on both sides, resulting in exceptional tear strength designed for expedition use.",
    "category": "Proprietary Fabrics",
    "aliases": [
      "Hilleberg Fabric"
    ]
  },
  {
    "name": "Hydrostatic Head",
    "Definition": "A laboratory measure of waterproofness indicating the vertical height of a column of water (in millimeters) that a fabric can support before water penetrates through the weave.",
    "category": "Fabric Testing",
    "aliases": [
      "HH",
      "Water Column",
      "HH Rating"
    ]
  },
  {
    "name": "DWR",
    "Definition": "A polymer coating applied to the face fabric of outerwear and tents that lowers surface tension, causing water to bead up and roll off rather than soaking into the fibers (wetting out).",
    "category": "Chemical Treatments",
    "aliases": [
      "Durable Water Repellent",
      "Hydrophobic Coating"
    ]
  },
  {
    "name": "Dome Tent",
    "Definition": "A shelter structure formed by two flexible poles crossing at the apex, creating a square or rectangular base. They generally offer good headroom and are freestanding.",
    "category": "Shelter Geometry",
    "aliases": [
      "Cross-pole tent"
    ]
  },
  {
    "name": "Tunnel Tent",
    "Definition": "A tent design using parallel hoops creating a tunnel shape. They offer excellent space-to-weight ratios but are non-freestanding and rely entirely on guy lines and stakes for structure.",
    "category": "Shelter Geometry",
    "aliases": [
      "Hoop tent"
    ]
  },
  {
    "name": "Geodesic Tent",
    "Definition": "A complex dome structure where poles intersect at three or more points, creating triangles for structural rigidity. Designed for handling static snow loads and dynamic wind loading in extreme conditions.",
    "category": "Shelter Geometry",
    "aliases": [
      "Expedition Dome"
    ]
  },
  {
    "name": "Bivy Sack",
    "Definition": "A waterproof/breathable slipcover for a sleeping bag, originally designed for emergency alpine bivouacs or ultralight travel where a full tent is impractical.",
    "category": "Ultralight Shelter",
    "aliases": [
      "Bivouac Sack",
      "Bivi",
      "Bivvy Bag"
    ]
  },
  {
    "name": "Down Insulation",
    "Definition": "The soft under-feathers of waterfowl used for insulation. It offers the best warmth-to-weight ratio but loses insulating value when wet.",
    "category": "Insulation",
    "aliases": [
      "Goose Down",
      "Duck Down",
      "Plumage"
    ]
  },
  {
    "name": "Synthetic Insulation",
    "Definition": "Man-made polyester fibers engineered to mimic the structure of down. While heavier and less compressible than down, it retains insulating value when wet.",
    "category": "Insulation",
    "aliases": [
      "Primaloft",
      "Climashield",
      "Polarguard",
      "Coreloft"
    ]
  },
  {
    "name": "Backpacking Quilt",
    "Definition": "A sleep system that removes the hood and back insulation found in traditional sleeping bags (which is compressed and thermally useless under the body), relying instead on a sleeping pad for bottom insulation to save weight.",
    "category": "Sleep System",
    "aliases": [
      "Top Quilt"
    ]
  },
  {
    "name": "R-Value",
    "Definition": "A measure of thermal resistance used to rate sleeping pads, indicating the material's ability to resist the flow of heat from the body to the cold ground.",
    "category": "Insulation Metrics",
    "aliases": [
      "Thermal Resistance"
    ]
  },
  {
    "name": "Merino Wool",
    "Definition": "A natural fiber from Merino sheep that regulates body temperature and resists odors. It has an exothermic reaction with moisture, generating a small amount of heat when damp.",
    "category": "Apparel",
    "aliases": [
      "Wool"
    ]
  },
  {
    "name": "Vapor Barrier Liner",
    "Definition": "A non-breathable, waterproof layer worn next to the skin in extreme cold to prevent perspiration from entering insulation layers and condensing, thus preserving the loft of outer gear.",
    "category": "Specialized Clothing",
    "aliases": [
      "VBL"
    ]
  },
  {
    "name": "Zero Drop",
    "Definition": "A footwear design where the heel and forefoot are at the same height off the ground (0mm differential), promoting a midfoot strike but increasing load on the Achilles tendon.",
    "category": "Footwear Geometry",
    "aliases": [
      "0mm Drop",
      "Balanced Cushioning"
    ]
  },
  {
    "name": "Stack Height",
    "Definition": "The total amount of material (outsole, midsole, and insole) between the foot and the ground, measured in millimeters.",
    "category": "Footwear Geometry",
    "aliases": [
      "Sole Thickness"
    ]
  },
  {
    "name": "Rock Plate",
    "Definition": "A hard plastic or carbon fiber insert sandwiched between the midsole and outsole of a trail shoe to protect the foot from sharp rocks.",
    "category": "Footwear Component",
    "aliases": [
      "Stone Guard"
    ]
  },
  {
    "name": "Canister Stove",
    "Definition": "A cooking stove that uses pre-pressurized gas canisters (Isobutane/Propane). They are convenient and fast but can struggle in extreme cold due to pressure drops.",
    "category": "Backcountry Kitchen",
    "aliases": [
      "Gas Stove"
    ]
  },
  {
    "name": "Alcohol Stove",
    "Definition": "A simple stove, often homemade, that burns denatured alcohol. They are silent and fail-safe but have lower heat output and are sensitive to wind.",
    "category": "Backcountry Kitchen",
    "aliases": [
      "Spirit Burner",
      "Cat Can Stove"
    ]
  },
  {
    "name": "Personal Locator Beacon",
    "Definition": "An emergency device that sends a one-way distress signal via the COSPAS-SARSAT government satellite system to rescue coordination centers. It does not allow for messaging.",
    "category": "Emergency Electronics",
    "aliases": [
      "PLB"
    ]
  },
  {
    "name": "Satellite Messenger",
    "Definition": "A communication device using commercial satellite networks (like Iridium) to allow for two-way texting, GPS tracking, and SOS signaling.",
    "category": "Emergency Electronics",
    "aliases": [
      "InReach",
      "SPOT"
    ]
  },
  {
    "name": "Leave No Trace",
    "Definition": "An ethical framework for outdoor recreation designed to minimize human impact on the environment, consisting of seven core principles.",
    "category": "Ethics",
    "aliases": [
      "LNT"
    ]
  },
  {
    "name": "Hiker Trash",
    "Definition": "A slang term, often reclaimed as a badge of honor, describing long-distance hikers who are visually disheveled and reject societal norms of hygiene in favor of trail efficiency.",
    "category": "Trail Culture",
    "aliases": []
  },
  {
    "name": "Tramily",
    "Definition": "A portmanteau of 'Trail Family,' referring to a group of hikers who bond on the trail and share resources, emotional support, and hiking schedules.",
    "category": "Trail Culture",
    "aliases": [
      "Trail Family"
    ]
  },
  {
    "name": "Triple Crowner",
    "Definition": "A hiker who has completed the three major US National Scenic Trails: the Appalachian Trail (AT), Pacific Crest Trail (PCT), and Continental Divide Trail (CDT).",
    "category": "Trail Culture",
    "aliases": []
  },
  {
    "name": "Yogi-ing",
    "Definition": "The act of passively soliciting food or rides from strangers by striking up conversation and appearing needy without directly asking.",
    "category": "Trail Culture",
    "aliases": []
  },
  {
    "name": "Yellow Blazing",
    "Definition": "Skipping sections of a trail by driving or hitchhiking along the road.",
    "category": "Trail Culture",
    "aliases": []
  },
  {
    "name": "Blue Blazing",
    "Definition": "Taking side trails or alternative routes (often marked with blue blazes) instead of the official trail path.",
    "category": "Trail Culture",
    "aliases": []
  },
  {
    "name": "Slackpacking",
    "Definition": "Hiking a section of trail with only a light day pack while having full gear shuttled ahead by vehicle.",
    "category": "Trail Culture",
    "aliases": []
  },
  {
    "name": "Camel Up",
    "Definition": "Drinking a large volume of water at a source to fully hydrate before hiking on, reducing the water weight carried in the pack.",
    "category": "Trail Culture",
    "aliases": []
  },
  {
    "name": "Vitamin I",
    "Definition": "Slang for Ibuprofen, commonly used by hikers to manage chronic inflammation and joint pain.",
    "category": "Trail Slang",
    "aliases": [
      "Ibuprofen"
    ]
  },
  {
    "name": "Zero Day",
    "Definition": "A day during a long-distance hike where zero trail miles are walked, usually spent resting in town.",
    "category": "Trail Slang",
    "aliases": [
      "Zero"
    ]
  },
  {
    "name": "Nero Day",
    "Definition": "Short for 'Nearly Zero,' referring to a day with very low hiking mileage, typically used to enter or exit a town.",
    "category": "Trail Slang",
    "aliases": [
      "Nero"
    ]
  },
  {
    "name": "Hiker Box",
    "Definition": "A communal box found in hostels or post offices where hikers leave unwanted food and gear for others to take for free.",
    "category": "Logistics",
    "aliases": []
  },
  {
    "name": "Bounce Box",
    "Definition": "A package a hiker mails to themselves further up the trail containing items not needed for the current section or bulk supplies.",
    "category": "Logistics",
    "aliases": []
  }
]


if __name__ == "__main__":
    main()
