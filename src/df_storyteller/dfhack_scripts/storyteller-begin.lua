--- One-command setup for a new fortress in df-storyteller.
--- Run this once after embarking to set up everything the storyteller needs.
---
--- Usage:
---   storyteller-begin          -- Set up (skips legends by default)
---   storyteller-begin --yes    -- Set up + export legends
---   storyteller-begin --no     -- Set up, skip legends
---
--- Reference: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html

local json = require('json')

-- ======================= Config =======================
local world_folder = dfhack.world.ReadWorldFolder()
if world_folder == '' then
    dfhack.printerr('[storyteller] Error: No world loaded. Embark first, then run this command.')
    return
end
local output_dir = dfhack.getDFPath() .. '/storyteller_events/' .. world_folder .. '/'

local function get_season(tick)
    local season_tick = tick % 403200
    if season_tick < 100800 then return 'spring'
    elseif season_tick < 201600 then return 'summer'
    elseif season_tick < 302400 then return 'autumn'
    else return 'winter' end
end

local function ensure_output_dir()
    if not dfhack.filesystem.isdir(output_dir) then
        dfhack.filesystem.mkdir_recursive(output_dir)
    end
    local processed = output_dir .. 'processed/'
    if not dfhack.filesystem.isdir(processed) then
        dfhack.filesystem.mkdir_recursive(processed)
    end
end

-- Personality facet names in DF's internal order (always the same 50).
-- Ref: https://dwarffortresswiki.org/index.php/DF2014:Personality_facet
local FACET_NAMES = {
    'LOVE_PROPENSITY', 'HATE_PROPENSITY', 'ENVY_PROPENSITY',
    'CHEER_PROPENSITY', 'DEPRESSION_PROPENSITY', 'ANGER_PROPENSITY',
    'ANXIETY_PROPENSITY', 'LUST_PROPENSITY', 'STRESS_VULNERABILITY',
    'GREED', 'IMMODERATION', 'VIOLENT', 'PERSEVERANCE', 'WASTEFULNESS',
    'DISCORD', 'FRIENDLINESS', 'POLITENESS', 'DISDAIN_ADVICE',
    'BRAVERY', 'CONFIDENCE', 'VANITY', 'AMBITION', 'GRATITUDE',
    'IMMODESTY', 'HUMOR', 'VENGEFUL', 'PRIDE', 'CRUELTY',
    'SINGLEMINDED', 'HOPEFUL', 'CURIOUS', 'BASHFUL', 'PRIVACY',
    'PERFECTIONIST', 'CLOSEMINDED', 'TOLERANT', 'EMOTIONALLY_OBSESSIVE',
    'SWAYED_BY_EMOTIONS', 'ALTRUISM', 'DUTIFULNESS', 'THOUGHTLESSNESS',
    'ORDERLINESS', 'TRUST', 'GREGARIOUSNESS', 'ASSERTIVENESS',
    'ACTIVITY_LEVEL', 'EXCITEMENT_SEEKING', 'IMAGINATION',
    'ABSTRACT_INCLINED', 'ART_INCLINED',
}

--- Safe name translation. Tries multiple methods for DF version compatibility.
--- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html
local function safe_translate_name(name_obj, in_english)
    if not name_obj then return '' end
    local result = ''
    -- Method 1: dfhack.translation.translateName (documented API)
    pcall(function()
        result = dfhack.translation.translateName(name_obj, in_english)
    end)
    -- Method 2: dfhack.TranslateName (older API)
    if result == '' then
        pcall(function()
            result = dfhack.TranslateName(name_obj, in_english)
        end)
    end
    -- Convert DF encoding to UTF-8
    if result ~= '' then
        pcall(function() result = dfhack.df2utf(result) end)
    end
    return result
end

--- Safe readable unit name with UTF-8 encoding.
local function safe_unit_name(unit)
    local name = ''
    pcall(function()
        name = dfhack.units.getReadableName(unit)
        pcall(function() name = dfhack.df2utf(name) end)
    end)
    return name
end

-- ======================= Fortress Info =======================

local function get_fortress_info()
    local info = {
        world_folder = world_folder,
        fortress_name = '', site_name = '', site_type = '',
        biome = '', civ_name = '', civ_id = -1,
    }

    -- Fortress/site name
    pcall(function()
        local site = dfhack.world.getCurrentSite()
        if site then
            info.fortress_name = safe_translate_name(site.name, false)
            info.site_name = safe_translate_name(site.name, true)
            info.site_type = df.world_site_type[site.type] or ''
        end
    end)

    -- Try plotinfo name as fallback
    if info.fortress_name == '' then
        pcall(function()
            info.fortress_name = safe_translate_name(df.global.plotinfo.name, false)
            info.site_name = safe_translate_name(df.global.plotinfo.name, true)
        end)
    end

    -- Civilization name
    pcall(function()
        local civ_id = df.global.plotinfo.civ_id
        info.civ_id = civ_id
        local civ = df.historical_entity.find(civ_id)
        if civ then
            info.civ_name = safe_translate_name(civ.name, true)
        end
    end)

    -- Biome — try multiple approaches for version compatibility
    -- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html

    -- Method 1: getBiomeType from a map tile in the fortress
    pcall(function()
        local cx = math.floor(df.global.world.map.x_count / 2)
        local cy = math.floor(df.global.world.map.y_count / 2)
        -- Find a valid z-level (surface)
        for z = df.global.world.map.z_count - 1, 0, -1 do
            local rgn_x, rgn_y = dfhack.maps.getTileBiomeRgn(cx, cy, z)
            if rgn_x then
                local biome_type = dfhack.maps.getBiomeType(rgn_x, rgn_y)
                if biome_type then
                    info.biome = df.biome_type[biome_type] or tostring(biome_type)
                    break
                end
            end
        end
    end)

    -- Method 2: Read from site's position on the world map
    if info.biome == '' then
        pcall(function()
            local site = dfhack.world.getCurrentSite()
            if site and site.pos then
                local biome_type = dfhack.maps.getBiomeType(site.pos.x, site.pos.y)
                if biome_type then
                    info.biome = df.biome_type[biome_type] or tostring(biome_type)
                end
            end
        end)
    end

    -- Method 3: Direct region_map access
    if info.biome == '' then
        pcall(function()
            local site = dfhack.world.getCurrentSite()
            if site then
                -- Try various position fields
                local wx, wy
                pcall(function() wx = site.pos.x; wy = site.pos.y end)
                if not wx then pcall(function() wx = site.global_min_x; wy = site.global_min_y end) end
                if wx and wy and df.global.world.world_data then
                    local region = df.global.world.world_data.region_map[wx]:_displace(wy)
                    if region and region.biome then
                        info.biome = df.biome_type[region.biome] or tostring(region.biome)
                    end
                end
            end
        end)
    end

    -- Method 4: Just describe from map features if all else fails
    if info.biome == '' then
        pcall(function()
            local site = dfhack.world.getCurrentSite()
            if site and site.type then
                -- At least capture the site type as a hint
                info.biome = 'unknown (site type: ' .. (df.world_site_type[site.type] or '') .. ')'
            end
        end)
    end

    return info
end

-- ======================= Unit Serializer =======================

local function serialize_unit(unit)
    local unit_age = 0
    pcall(function() unit_age = dfhack.units.getAge(unit) or 0 end)

    local data = {
        unit_id = unit.id,
        name = safe_unit_name(unit),
        race = df.creature_raw.find(unit.race).creature_id,
        profession = dfhack.units.getProfessionName(unit),
        is_alive = dfhack.units.isAlive(unit),
        stress_category = dfhack.units.getStressCategory(unit),
        age = unit_age,
        civ_id = unit.civ_id,
        skills = {},
        personality = { facets = {}, beliefs = {}, goals = {} },
        relationships = {},
        noble_positions = {},
        military = {},
        physical_attributes = {},
        mental_attributes = {},
        current_job = '',
        equipment = {},
        wounds = {},
    }

    local soul = unit.status and unit.status.current_soul

    -- Skills
    if soul and soul.skills then
        for _, skill in ipairs(soul.skills) do
            if skill.rating > 0 then
                -- Get readable skill name from enum
                -- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html
                local skill_name = tostring(skill.id)
                pcall(function()
                    -- Try caption first (human-readable)
                    skill_name = df.job_skill.attrs[skill.id].caption or skill_name
                end)
                if skill_name == tostring(skill.id) then
                    -- Fall back to enum key name (e.g. MINING)
                    pcall(function() skill_name = df.job_skill[skill.id] or skill_name end)
                end
                table.insert(data.skills, {
                    name = skill_name,
                    level = skill.rating,
                    experience = skill.experience,
                })
            end
        end
    end

    -- Personality facets — map numeric indices to named traits
    pcall(function()
        if soul and soul.personality and soul.personality.traits then
            local traits = soul.personality.traits
            -- Try named fields first
            local named_ok = false
            pcall(function()
                for _, field in ipairs(traits._type.fields) do
                    local val = traits[field.name]
                    if val then
                        table.insert(data.personality.facets, { name = field.name, value = val })
                        named_ok = true
                    end
                end
            end)
            -- Fall back to numeric indices with our name mapping
            if not named_ok or #data.personality.facets == 0 then
                data.personality.facets = {}
                for i = 0, math.min(#traits - 1, #FACET_NAMES - 1) do
                    pcall(function()
                        local val = traits[i]
                        if val then
                            table.insert(data.personality.facets, {
                                name = FACET_NAMES[i + 1] or tostring(i),
                                value = val,
                            })
                        end
                    end)
                end
            end
        end
    end)

    -- Beliefs
    pcall(function()
        if soul and soul.personality and soul.personality.values then
            for _, v in ipairs(soul.personality.values) do
                table.insert(data.personality.beliefs, {
                    name = df.value_type[v.type] or tostring(v.type),
                    value = v.strength,
                })
            end
        end
    end)

    -- Goals
    pcall(function()
        -- Try getGoalType first
        local goals = dfhack.units.getGoalType(unit)
        if goals then
            for _, goal in ipairs(goals) do
                table.insert(data.personality.goals, {
                    name = df.goal_type[goal] or tostring(goal),
                    achieved = dfhack.units.isGoalAchieved(unit, goal) or false,
                })
            end
        end
        -- Also try direct access to soul dreams
        if #data.personality.goals == 0 and soul and soul.personality and soul.personality.dreams then
            for _, dream in ipairs(soul.personality.dreams) do
                pcall(function()
                    table.insert(data.personality.goals, {
                        name = df.goal_type[dream.type] or tostring(dream.type),
                        achieved = dream.flags.accomplished or false,
                    })
                end)
            end
        end
    end)

    -- Relationships: extract all from historical figure links (the reliable API)
    -- unit.relations/unit.relationship_ids vary between DF versions;
    -- histfig_links is consistent and covers family + social bonds.
    pcall(function()
        if unit.hist_figure_id and unit.hist_figure_id >= 0 then
            local hf = df.historical_figure.find(unit.hist_figure_id)
            if hf and hf.histfig_links then
                local seen_targets = {}

                -- Map link type class names to readable relationship types
                local link_type_names = {
                    histfig_hf_link_spousest = 'spouse',
                    histfig_hf_link_loverst = 'lover',
                    histfig_hf_link_motherst = 'mother',
                    histfig_hf_link_fatherst = 'father',
                    histfig_hf_link_childst = 'child',
                    histfig_hf_link_companionst = 'companion',
                    histfig_hf_link_deityst = 'deity',
                    histfig_hf_link_former_spousest = 'former spouse',
                    histfig_hf_link_former_loverst = 'former lover',
                }

                for _, link in ipairs(hf.histfig_links) do
                    pcall(function()
                        local target_hf_id = link.target_hf
                        if not target_hf_id or target_hf_id < 0 then return end

                        -- Determine relationship type from the link class name
                        local class_name = tostring(link._type):match('([%w_]+)>') or ''
                        local rel_type = link_type_names[class_name]
                        if not rel_type then
                            -- Fallback: try to read the type enum
                            pcall(function()
                                local enum_name = df.histfig_hf_link_type[link.type]
                                if enum_name then
                                    rel_type = tostring(enum_name):lower():gsub('_', ' ')
                                end
                            end)
                        end
                        if not rel_type then rel_type = 'associate' end

                        -- Find the unit on the map by their hist_figure_id
                        local target_unit = nil
                        for _, u in ipairs(df.global.world.units.active) do
                            if u.hist_figure_id == target_hf_id then
                                target_unit = u
                                break
                            end
                        end

                        -- Also resolve name from the historical figure if unit not on map
                        local target_name = ''
                        local target_id = -1
                        if target_unit then
                            target_name = safe_unit_name(target_unit)
                            target_id = target_unit.id
                        else
                            local target_hf = df.historical_figure.find(target_hf_id)
                            if target_hf then
                                pcall(function()
                                    target_name = dfhack.df2utf(dfhack.translation.translateName(target_hf.name, true))
                                end)
                                target_id = target_hf_id * -1  -- negative ID = off-map HF
                            end
                        end

                        if target_name ~= '' and not seen_targets[target_id] then
                            table.insert(data.relationships, {
                                type = rel_type,
                                target_name = target_name,
                                target_id = target_id,
                            })
                            seen_targets[target_id] = true
                        end
                    end)
                end
            end
        end

        -- Fallback: try unit.relationship_ids.Spouse if histfig didn't find one
        local has_spouse = false
        for _, rel in ipairs(data.relationships) do
            if rel.type == 'spouse' then has_spouse = true; break end
        end
        if not has_spouse then
            pcall(function()
                local spouse_id = unit.relationship_ids.Spouse
                if spouse_id and spouse_id >= 0 then
                    local spouse = df.unit.find(spouse_id)
                    if spouse then
                        table.insert(data.relationships, { type = 'spouse', target_name = safe_unit_name(spouse), target_id = spouse.id })
                    end
                end
            end)
        end
    end)

    -- Noble positions
    pcall(function()
        local positions = dfhack.units.getNoblePositions(unit)
        if positions then
            for _, pos in ipairs(positions) do
                pcall(function()
                    local pos_name = pos.position.name[0] or pos.position.name_male[0] or ''
                    if pos_name ~= '' then table.insert(data.noble_positions, pos_name) end
                end)
            end
        end
    end)

    -- Military
    pcall(function()
        if unit.military and unit.military.squad_id >= 0 then
            data.military = {
                squad_id = unit.military.squad_id,
                squad_position = unit.military.squad_position,
            }
            pcall(function() data.military.squad_name = dfhack.military.getSquadName(unit.military.squad_id) end)
        end
    end)

    -- Physical attributes
    pcall(function()
        if unit.body and unit.body.physical_attrs then
            local names = {'STRENGTH', 'AGILITY', 'TOUGHNESS', 'ENDURANCE', 'RECUPERATION', 'DISEASE_RESISTANCE'}
            for i, name in ipairs(names) do
                pcall(function() data.physical_attributes[name] = unit.body.physical_attrs[i-1].value end)
            end
        end
    end)

    -- Mental attributes
    pcall(function()
        if soul and soul.mental_attrs then
            local names = {'ANALYTICAL_ABILITY','FOCUS','WILLPOWER','CREATIVITY','INTUITION','PATIENCE','MEMORY','LINGUISTIC_ABILITY','SPATIAL_SENSE','MUSICALITY','KINESTHETIC_SENSE','EMPATHY','SOCIAL_AWARENESS'}
            for i, name in ipairs(names) do
                pcall(function() data.mental_attributes[name] = soul.mental_attrs[i-1].value end)
            end
        end
    end)

    -- Current job
    pcall(function()
        if unit.job and unit.job.current_job then
            data.current_job = df.job_type[unit.job.current_job.job_type] or ''
        end
    end)

    -- Equipment
    pcall(function()
        if unit.inventory then
            for _, inv in ipairs(unit.inventory) do
                local mode = df.unit_inventory_item.T_mode[inv.mode] or ''
                if mode == 'Worn' or mode == 'Weapon' or mode == 'Strapped' then
                    pcall(function()
                        local desc = dfhack.items.getDescription(inv.item, 0, true)
                        if desc and desc ~= '' then
                            table.insert(data.equipment, { description = desc, mode = mode })
                        end
                    end)
                end
            end
        end
    end)

    -- Wounds
    pcall(function()
        if unit.body and unit.body.wounds then
            for _, wound in ipairs(unit.body.wounds) do
                pcall(function()
                    for _, part in ipairs(wound.parts) do
                        pcall(function()
                            local raw = df.creature_raw.find(unit.race)
                            local bp = raw.caste[unit.caste].body_info.body_parts[part.body_part_id].name_singular[0].value
                            if bp then table.insert(data.wounds, bp) end
                        end)
                    end
                end)
            end
        end
    end)

    return data
end

-- ======================= Main =======================

print('')
print('=== df-storyteller: New Fortress Setup ===')
print('')

ensure_output_dir()

-- Step 0: Gather fortress info + unique session ID
-- The session ID is generated once per fortress instance and stored in a marker
-- file. This disambiguates different fortress attempts at the same site.
local session_id_path = output_dir .. '.session_id'
local fortress_session_id = ''
pcall(function()
    local f = io.open(session_id_path, 'r')
    if f then
        fortress_session_id = f:read('*a'):match('^%s*(.-)%s*$') or ''
        f:close()
    end
end)
if fortress_session_id == '' then
    fortress_session_id = tostring(os.time())
    pcall(function()
        local f = io.open(session_id_path, 'w')
        if f then
            f:write(fortress_session_id)
            f:close()
        end
    end)
    print('[storyteller] New fortress session: ' .. fortress_session_id)
end

local fortress_info = get_fortress_info()
fortress_info.session_id = fortress_session_id
if fortress_info.fortress_name ~= '' then
    print('[storyteller] Fortress: ' .. fortress_info.fortress_name)
end
if fortress_info.site_name ~= '' then
    print('[storyteller] Site: ' .. fortress_info.site_name)
end
if fortress_info.civ_name ~= '' then
    print('[storyteller] Civilization: ' .. fortress_info.civ_name)
end
if fortress_info.biome ~= '' then
    print('[storyteller] Biome: ' .. fortress_info.biome)
end
print('')

-- Step 1: Parse args
local do_legends = false
local snapshot_only = false
local args = { ... }
if args[1] == '--yes' or args[1] == '-y' then
    do_legends = true
elseif args[1] == '--no' or args[1] == '-n' then
    do_legends = false
elseif args[1] == '--snapshot-only' then
    snapshot_only = true
    do_legends = false
else
    print('Export world history for richer stories?')
    print('  Run: storyteller-begin --yes   (export legends)')
    print('  Run: storyteller-begin --no    (skip legends)')
    print('')
    print('Defaulting to: skip legends')
    print('')
end

if do_legends then
    print('[storyteller] Exporting world history...')
    local ok, err = pcall(function() dfhack.run_command('exportlegends', 'info') end)
    if ok then print('[storyteller] World history exported.')
    else print('[storyteller] Legends export failed (may need legends mode). Skipping.') end
end

-- Step 2: Snapshot units
print('[storyteller] Taking fortress snapshot...')

local player_race = df.global.plotinfo.race_id
local citizens = {}
local visitors = {}
local animals = {}

for _, unit in ipairs(df.global.world.units.active) do
    if dfhack.units.isAlive(unit) then
        local ok, data = pcall(serialize_unit, unit)
        if ok then
            if unit.race == player_race then
                data.role = 'citizen'
                table.insert(citizens, data)
            elseif dfhack.units.isAnimal(unit) or dfhack.units.isWildlife(unit) then
                data.role = 'animal'
                table.insert(animals, data)
            elseif dfhack.units.isVisiting(unit) then
                -- Actual visitors: merchants, diplomats, travelers
                data.role = 'visitor'
                table.insert(visitors, data)
            end
            -- Everything else (underground creatures, etc.) is silently skipped
        end
    end
end

-- Buildings
local buildings = {}
for _, building in ipairs(df.global.world.buildings.all) do
    local ok, data = pcall(function()
        return {
            building_type = df.building_type[building:getType()] or 'unknown',
            name = dfhack.buildings.getName(building) or '',
            position = { x = building.centerx, y = building.centery, z = building.z },
        }
    end)
    if ok then table.insert(buildings, data) end
end

-- Write snapshot
local year = df.global.cur_year
local tick = df.global.cur_year_tick
local season = get_season(tick)

local snapshot = {
    event_type = 'snapshot',
    game_year = year,
    game_tick = tick,
    season = season,
    data = {
        fortress_info = fortress_info,
        population = #citizens,
        citizens = citizens,
        visitors = visitors,
        animals = animals,
        buildings = buildings,
    },
}

-- Use a unique filename to avoid overwrite issues
local filename = string.format('snapshot_%d_%06d_%d', year, tick, os.time())
local tmp_path = output_dir .. filename .. '.tmp'
local json_path = output_dir .. filename .. '.json'

local write_ok, write_err = pcall(function()
    local f = io.open(tmp_path, 'w')
    f:write(json.encode(snapshot))
    f:close()
end)

if write_ok then
    local rename_ok = os.rename(tmp_path, json_path)
    if not rename_ok then
        -- If rename fails, the tmp file still has the data — just use it directly
        json_path = tmp_path
    end
end

print(string.format('[storyteller] Snapshot: %d citizens, %d visitors, %d animals, %d buildings',
    #citizens, #visitors, #animals, #buildings))

for _, c in ipairs(citizens) do
    local extras = {}
    if #c.noble_positions > 0 then table.insert(extras, table.concat(c.noble_positions, ', ')) end
    local mil = c.military or {}
    if type(mil) == 'table' and mil.squad_name and mil.squad_name ~= '' then table.insert(extras, mil.squad_name) end
    if #c.personality.facets > 0 then table.insert(extras, #c.personality.facets .. ' traits') end
    local suffix = #extras > 0 and (' [' .. table.concat(extras, ', ') .. ']') or ''
    print(string.format('  - %s (%s, age %d)%s', c.name, c.profession, math.floor(c.age), suffix))
end

-- Step 3: Start event monitoring (skip if snapshot-only)
if not snapshot_only then
    print('')
    print('[storyteller] Starting event monitoring...')
    dfhack.run_command('storyteller-events', 'start')

    print('')
    print('=== Setup complete! ===')
    print('')
    print('Play the game, then in your terminal:')
    print('  python -m df_storyteller chronicle')
    print('  python -m df_storyteller bio "name"')
    print('  python -m df_storyteller dwarves')
    print('')
else
    print('')
    print('[storyteller] Snapshot saved.')
    print('')
end
