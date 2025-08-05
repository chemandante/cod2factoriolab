import io
import json
import re
import sys

import wand.image
from PIL import Image

INPUT_PATH = "./in/"
OUTPUT_PATH = "./out/"

REX_Product = re.compile(r'Product_(Virtual_)?([A-Za-z0-9]+)')
REX_ProdType = re.compile(r'([A-Z][a-z0-9]+)ProductProto')
REX_CoDNaming = re.compile(r'[A-Z][a-z]+|[A-Z]{2,}|\d[A-Z]?')

PRODUCT_TYPES = {'Countable': {'name': 'Unit resources', 'icon': 'iron'},
                 'Fluid': {'name': 'Fluid resources', 'icon': 'water'},
                 'Loose': {'name': 'Loose resources', 'icon': 'gravel'},
                 'Molten': {'name': 'Molten resources', 'icon': 'molten-iron'},
                 'Virtual': {'name': 'Virtual resources', 'icon': 'maintenance-1'}
                 }

# Products (including virtual) that is not listed in input files from CoD
DEFAULT_PRODUCTS = {'worker': 'Workers'}

ICON_SIZE = 64


def convertCod2FL(codName: str) -> str:
    """
    Converts names from Captain-of-Data (CoD) dump to Factoriolab-style naming
    :param codName: Name in CoD, ex. 'MaintenanceT2' or 'CopperImpure'
    :return: Name in Factoriolab style, ex. 'maintenance-2' or 'copper-impure'
    """
    return '-'.join(REX_CoDNaming.findall(codName)).lower()


def convertIngredientList(ingredients: list[dict]) -> dict:
    """
    Converts ingredient list from CoD format to Factoriolab-style dict
    :param ingredients: source list of dicts {'name': <product name>, 'quantity': <quantity>}
    :return: dict {<product ID>: <quantity>}
    """
    ret = {}
    for ingredient in ingredients:
        prodID = prodIndex.get(ingredient['name'], None)
        if prodID is None:
            raise ValueError(f'Unknown ingredient: {ingredient['name']}')
        ret[prodID] = ingredient['quantity']

    return ret


def getCategories() -> list[dict]:
    """
    Getting list of categories for output JSON
    :return: list of dict
    """
    rl = []
    for key, data in PRODUCT_TYPES.items():
        rl.append({'id': key.lower(), 'name': data['name'], 'icon': data['icon']})
    return rl


def getIcons() -> list[dict]:
    """
    Make icon sprite sheet and write in to 'icons.webp'
    :return: None
    """
    cnt = 0
    rl = []
    for icon in sorted(iconList, key=lambda x: x['id']):
        rl.append({'id': icon['id'], 'position': f'-{cnt % 1216}px -{(cnt // 1216) * 64}px', 'color': '#000000'})
        cnt += 40
    return rl


def getItems() -> list[dict]:
    """
    Getting list of items for output JSON
    :return: list of dict
    """
    rl = []
    for x in prodList:
        rl.append({'id': x['id'], 'name': x['name'], 'category': x['type'], 'row': 0})
    rl.extend(mnbList)
    return rl


ids = set()
iconList = []
prodList = []
prodIndex = {}
mnbList = []
recipeIds = {}
recipeList = []

# Adding defaults
for prod, name in DEFAULT_PRODUCTS.items():
    prodList.append({'id': prod, 'name': name, 'type': 'virtual'})
    prodIndex[name] = prod

# Read products
with open(INPUT_PATH + 'data/products.json', encoding='utf-8') as f:
    inData = json.load(f)
    version = inData['game_version']

    for item in inData['products']:
        typeStr = item['type']
        res = REX_ProdType.match(typeStr)
        if res is None or res.group(1) not in PRODUCT_TYPES:
            print(f'Strange product type: \'{typeStr}\'')
            continue
        typeStr = res.group(1)

        idStr: str = item['id']
        res = REX_Product.match(idStr)
        if res is None:
            print(f'Strange product ID: \'{idStr}\'')
            continue

        flabID = convertCod2FL(res.group(2))
        if flabID in ids:
            print(f'Duplicate product ID {flabID}')
            continue
        r = {'id': flabID,
             'name': item['name'],
             'type': typeStr.lower()}
        prodList.append(r)
        # Adding to index
        if item['name'] in prodIndex:
            print(f'Duplicate name \'{item["name"]}\'')
            continue
        prodIndex[item['name']] = flabID

        # Adding icon
        iconList.append({'id': flabID, 'icon': item['icon_path']})


# Read machines, buildings and recipes
with open(INPUT_PATH + "data/machines_and_buildings.json", encoding="utf-8") as f:
    inData = json.load(f)
    if inData["game_version"] != version:
        print("Game version differs in 'machines_and_buildings.json'")
        sys.exit(1)

    # Process every item and build separate lists of machines and recipes
    for item in inData['machines_and_buildings']:
        #********************
        #  Process building
        #********************
        flabID = convertCod2FL(item['id'])
        if flabID in ids:
            print(f'Duplicate building ID {flabID}')
            continue
        # Fill new dictionary
        r = {'id': flabID,
             'name': item['name'],
             'category': 'buildings'
            }
        # Fill consumptions
        r_cons = {}
        # Calc workers
        if item['workers'] > 0:
            r_cons['worker'] = item['workers']
        # Calc electricity
        if item['electricity_consumed'] > 0:
            r_cons['electricity'] = item['electricity_consumed']
        # Calc maintenance
        unit = item['maintenance_cost_units']
        if unit != '':
            unit = prodIndex.get(item['maintenance_cost_units'], None)
            if unit is None:
                print(f'Unknown maintenance unit \'{item['maintenance_cost_units']}\' in {flabID}')
                continue
            r_cons[unit] = item['maintenance_cost_quantity']

        # Add to main dict
        r['machine'] = {'speed': 1, 'consumption': r_cons}
        mnbList.append(r)

        # Adding icon
        iconList.append({'id': flabID, 'icon': item['icon_path']})

        #*******************
        #  Process recipes
        #*******************
        for recipe in item['recipes']:
            rID = convertCod2FL(recipe['id'])
            rCnt = recipeIds.get(rID, 0)
            # If there was already a recipe with this id, mark others with suffix -a, -b, ...
            if rCnt > 0:
                rCnt += 1
                recipeIds[rID] = rCnt
                rID += '-' + chr(95 + rCnt)
            else:
                recipeIds[rID] = 1

            r = {'id': rID,
                 'name': recipe['name'],
                 'time': recipe['duration'],
                 'producers': [flabID],
                 'row': 0,
                 'icon': flabID} # "category": ???
            try:
                r['in'] = convertIngredientList(recipe['inputs'])
                r['out'] = convertIngredientList(recipe['outputs'])
            except ValueError as e:
                print(f'ValueError: {e}')
                continue

            if r['out']:
                recipeList.append(r)

# Preparing output
output = {'version': {'Captain of Industry': version},
          'categories': getCategories(),
          'icons': getIcons(),
          'items': getItems(),
          #'bld': mnbList,
          'recipes': recipeList,
          # 'idx': prodIndex
          }

with open(OUTPUT_PATH + 'data.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=4)
