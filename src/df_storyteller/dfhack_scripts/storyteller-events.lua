--- Real-time event listener for df-storyteller.
--- Captures game events and writes them as JSON files for the Python app.
---
--- Usage:
---   storyteller-events start    -- Enable event monitoring
---   storyteller-events stop     -- Disable event monitoring
---   storyteller-events status   -- Show monitoring status
---
--- Reference: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html
--- Key modules: dfhack.units, dfhack.world, eventful plugin

-- Guard: fortress mode only (gamemode 0 = DWARF, 1 = ADVENTURE)
if df.global.gamemode ~= 0 then
    local mode_name = tostring(df.global.gamemode)
    pcall(function() mode_name = df.game_mode[df.global.gamemode] or mode_name end)
    print('[storyteller] Skipping: this script requires fortress mode (current: ' .. mode_name .. ').')
    return
end

local eventful = require('plugins.eventful')
local json = require('json')

-- ======================= Config =======================
-- Per-world subfolder so multiple worlds don't mix data.
-- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html
local world_folder = dfhack.world.ReadWorldFolder()
local output_dir = dfhack.getDFPath() .. '/storyteller_events/' .. world_folder .. '/'
local poll_interval_ticks = 100

-- Read fortress session ID and validate it matches the current fortress.
-- If the folder was reused by a different fortress (e.g. "autosave 1" overwritten),
-- generate a new session_id so old events don't contaminate the new fortress.
local fortress_session_id = ''
pcall(function()
    -- Get current fortress identity
    local current_civ_id = df.global.plotinfo.civ_id
    local current_site_id = -1
    local current_name = ''
    pcall(function()
        local site = dfhack.world.getCurrentSite()
        if site then
            current_site_id = site.id
            current_name = dfhack.df2utf(dfhack.translation.translateName(site.name, false))
        end
        if current_name == '' then
            current_name = dfhack.df2utf(dfhack.translation.translateName(df.global.plotinfo.name, false))
        end
    end)

    local existing_info = nil

    -- Try new-format .session_info (has identity validation)
    local f = io.open(output_dir .. '.session_info', 'r')
    if f then
        local content = f:read('*a')
        f:close()
        existing_info = json.decode(content)
        if existing_info and existing_info.session_id and existing_info.session_id ~= '' then
            local stored_site_id = existing_info.site_id or -1
            local match = false
            if current_site_id >= 0 and stored_site_id >= 0 then
                match = (stored_site_id == current_site_id)
            else
                match = (existing_info.civ_id == current_civ_id and existing_info.fortress_name == current_name)
            end
            if match then
                fortress_session_id = existing_info.session_id
                return
            else
                -- Check if reclaiming a previously-played fortress
                local site_key = tostring(current_site_id)
                local by_site = existing_info.session_ids_by_site or {}
                if current_site_id >= 0 and by_site[site_key] then
                    print('[storyteller-events] Reclaiming previously-played fortress (site ' .. site_key .. ')')
                else
                    print('[storyteller-events] Session mismatch — folder reused by different fortress')
                end
            end
        end
    end

    -- Fallback: legacy .session_id (no validation, but try it)
    f = io.open(output_dir .. '.session_id', 'r')
    if f then
        local sid = f:read('*a'):match('^%s*(.-)%s*$') or ''
        f:close()
        if sid ~= '' then
            print('[storyteller-events] Legacy session_id found, cannot validate — generating new')
        end
    end

    -- Generate new session_id
    fortress_session_id = tostring(os.time())

    -- Build session_ids_by_site preserving history across retire/reclaim cycles
    local session_ids_by_site = {}
    if existing_info and existing_info.session_ids_by_site then
        session_ids_by_site = existing_info.session_ids_by_site
    end
    if existing_info and existing_info.session_id and existing_info.site_id then
        local old_key = tostring(existing_info.site_id)
        if not session_ids_by_site[old_key] then
            session_ids_by_site[old_key] = {}
        end
        local found = false
        for _, sid in ipairs(session_ids_by_site[old_key]) do
            if sid == existing_info.session_id then found = true; break end
        end
        if not found then
            table.insert(session_ids_by_site[old_key], existing_info.session_id)
        end
    end
    if current_site_id >= 0 then
        local cur_key = tostring(current_site_id)
        if not session_ids_by_site[cur_key] then
            session_ids_by_site[cur_key] = {}
        end
        local found = false
        for _, sid in ipairs(session_ids_by_site[cur_key]) do
            if sid == fortress_session_id then found = true; break end
        end
        if not found then
            table.insert(session_ids_by_site[cur_key], fortress_session_id)
        end
    end

    -- Write updated .session_info and legacy .session_id
    if not dfhack.filesystem.isdir(output_dir) then
        dfhack.filesystem.mkdir_recursive(output_dir)
    end
    pcall(function()
        local info = {
            session_id = fortress_session_id,
            civ_id = current_civ_id,
            site_id = current_site_id,
            fortress_name = current_name,
            session_ids_by_site = session_ids_by_site,
        }
        local wf = io.open(output_dir .. '.session_info', 'w')
        if wf then
            wf:write(json.encode(info))
            wf:close()
        end
    end)
    pcall(function()
        local wf = io.open(output_dir .. '.session_id', 'w')
        if wf then
            wf:write(fortress_session_id)
            wf:close()
        end
    end)
    print('[storyteller-events] New fortress session: ' .. fortress_session_id)
end)

local event_flags = {
    death = true,
    combat = true,
    mood = true,
    birth = true,
    building_created = true,
    job_completed = true,
    season_change = true,
    mandate = true,
    crime = true,
    caravan = true,
    siege = true,
}

--- Get the current season name from the year tick.
--- DF year has 403200 ticks. Each season is 100800 ticks.
-- ======================= State =======================
-- Use a global table so state persists across script invocations.
-- DFHack runs the script fresh each time a command is issued,
-- so local variables would reset. dfhack.storyteller_state survives.
-- MUST be declared before any functions that reference 'state'.
if not dfhack.storyteller_state then
    dfhack.storyteller_state = {
        enabled = false,
        last_season = nil,
        known_unit_ids = {},
        sequence = 0,
        prev_professions = {},
        prev_nobles = {},
        prev_squads = {},
        prev_population = 0,
        prev_stress = {},
        poll_count = 0,
        prev_mandates = {},
        prev_crimes = {},
        peak_population = 0,
        death_count = 0,
        known_caravans = {},
        siege_active = false,
    }
end
local state = dfhack.storyteller_state

-- Detect map change: if the output directory changed (different world/save slot),
-- force a stop so start() will re-initialize with the correct output_dir.
-- Without this, the old tick callback keeps writing to the previous folder.
if state.enabled and state.output_dir and state.output_dir ~= output_dir then
    print('[storyteller] Map changed (' .. state.output_dir .. ' -> ' .. output_dir .. '), restarting...')
    eventful.onUnitDeath.storyteller = nil
    eventful.onBuildingCreatedDestroyed.storyteller = nil
    eventful.onJobCompleted.storyteller = nil
    state.enabled = false
    state.known_unit_ids = {}
    state.prev_professions = {}
    state.prev_nobles = {}
    state.prev_squads = {}
    state.prev_stress = {}
    state.prev_population = 0
    state.prev_mandates = {}
    state.prev_crimes = {}
    state.peak_population = 0
    state.death_count = 0
    state.known_caravans = {}
    state.siege_active = false
    state.sequence = 0
    state.poll_count = 0
end
state.output_dir = output_dir

local function get_season(tick)
    local season_tick = tick % 403200
    if season_tick < 100800 then
        return 'spring'
    elseif season_tick < 201600 then
        return 'summer'
    elseif season_tick < 302400 then
        return 'autumn'
    else
        return 'winter'
    end
end

-- DF calendar: 12 months, 28 days each, 1200 ticks per day
local MONTH_NAMES = {
    'Granite', 'Slate', 'Felsite',       -- spring
    'Hematite', 'Malachite', 'Galena',   -- summer
    'Limestone', 'Sandstone', 'Timber',  -- autumn
    'Moonstone', 'Opal', 'Obsidian',     -- winter
}

local function get_date(tick)
    local day_of_year = math.floor((tick % 403200) / 1200)
    local month = math.floor(day_of_year / 28) + 1
    local day = (day_of_year % 28) + 1
    return {
        month = math.min(month, 12),
        month_name = MONTH_NAMES[math.min(month, 12)] or 'Unknown',
        day = day,
    }
end

--- Ensure the output directory exists.
--- Uses dfhack.filesystem since os.execute is not available in DFHack's sandbox.
--- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html
local function ensure_output_dir()
    if not dfhack.filesystem.isdir(output_dir) then
        dfhack.filesystem.mkdir_recursive(output_dir)
    end
    local processed = output_dir .. 'processed/'
    if not dfhack.filesystem.isdir(processed) then
        dfhack.filesystem.mkdir_recursive(processed)
    end
end

--- Write a JSON event file atomically (write .tmp then rename to .json).
local function write_event(event_type, data)
    state.sequence = state.sequence + 1

    local year = df.global.cur_year
    local tick = df.global.cur_year_tick
    local season = get_season(tick)

    local date = get_date(tick)

    local event = {
        event_type = event_type,
        game_year = year,
        game_tick = tick,
        season = season,
        month_name = date.month_name,
        day = date.day,
        session_id = fortress_session_id,
        data = data,
    }

    local filename = string.format('%d_%s_%06d', year, event_type, state.sequence)
    local tmp_path = output_dir .. filename .. '.tmp'
    local json_path = output_dir .. filename .. '.json'

    local ok, err = pcall(function()
        local f = io.open(tmp_path, 'w')
        if not f then
            error('Cannot open file: ' .. tmp_path)
        end
        f:write(json.encode(event))
        f:close()
        os.rename(tmp_path, json_path)
    end)

    if not ok then
        dfhack.printerr('[storyteller] Error writing event: ' .. tostring(err))
    end
end

--- Check if a unit is one of our fortress dwarves.
--- Uses isFortControlled + race check instead of isCitizen for broader coverage.
--- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html#units-module
local function is_our_dwarf(unit)
    return dfhack.units.isAlive(unit)
        and unit.race == df.global.plotinfo.race_id
        and dfhack.units.isFortControlled(unit)
end

-- ======================= Helpers =======================

--- Serialize a unit into a table suitable for JSON output.
--- Uses dfhack.units API: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html#units-module
local function serialize_unit(unit)
    if not unit then return nil end

    local ok, result = pcall(function()
        local name = dfhack.units.getReadableName(unit)
        pcall(function() name = dfhack.df2utf(name) end)
        return {
            unit_id = unit.id,
            name = name,
            race = df.creature_raw.find(unit.race).creature_id,
            profession = dfhack.units.getProfessionName(unit),
            is_citizen = dfhack.units.isCitizen(unit),
            stress_category = dfhack.units.getStressCategory(unit),
            sex = unit.sex == 0 and 'female' or (unit.sex == 1 and 'male' or 'unknown'),
        }
    end)

    if ok then
        return result
    else
        dfhack.printerr('[storyteller] Error serializing unit ' .. tostring(unit.id) .. ': ' .. tostring(result))
        return { unit_id = unit.id, name = 'Unknown', race = '', profession = '' }
    end
end

--- Get notable skills for a unit (Legendary and above).
local function get_notable_skills(unit)
    local skills = {}
    if unit.status and unit.status.current_soul then
        local soul = unit.status.current_soul
        if soul.skills then
            for _, skill in ipairs(soul.skills) do
                if skill.rating >= 15 then
                    local ok, name = pcall(df.job_skill, skill.id)
                    table.insert(skills, {
                        skill = ok and name or tostring(skill.id),
                        level = 'Legendary',
                    })
                end
            end
        end
    end
    return skills
end

-- ======================= Event Handlers =======================

--- Handle unit attack events (fires per-blow).
--- Hook: eventful.onUnitAttack(attacker_id, defender_id, wound_id)
--- We aggregate blows into engagements and flush them periodically.
--- Hook: eventful.onReport(report_id) collects combat text for rich descriptions.
if not state.pending_combat then
    state.pending_combat = {}  -- key: "attacker_id:defender_id" -> {attacker, defender, blows, last_tick, weapon, report_lines}
end
if not state.last_combat_key then
    state.last_combat_key = nil  -- tracks which pending_combat entry gets report text
end

local function on_unit_attack(attacker_id, defender_id, wound_id)
    if not event_flags.combat then return end

    pcall(function()
        local attacker = df.unit.find(attacker_id)
        local defender = df.unit.find(defender_id)
        if not attacker or not defender then return end

        local key = tostring(attacker_id) .. ':' .. tostring(defender_id)
        local tick = df.global.cur_year_tick

        if not state.pending_combat[key] then
            -- Get weapon from attacker's main hand item
            local weapon_name = ''
            pcall(function()
                local weapon = dfhack.items.getItemAtPosition(attacker.pos)
                if attacker.body and attacker.body.weapon_bp >= 0 then
                    -- Try to find wielded weapon via inventory
                    for _, inv_item in ipairs(attacker.inventory) do
                        if inv_item.mode == 1 then  -- 1 = Weapon (T_mode enum may be nil in DF Premium)
                            weapon_name = dfhack.items.getDescription(inv_item.item, 0, false) or ''
                            break
                        end
                    end
                end
            end)

            state.pending_combat[key] = {
                attacker = serialize_unit(attacker),
                defender = serialize_unit(defender),
                blows = 0,
                weapon = weapon_name,
                first_tick = tick,
                last_tick = tick,
                is_lethal = false,
                report_lines = {},
            }
        end

        local entry = state.pending_combat[key]
        entry.blows = entry.blows + 1
        entry.last_tick = tick
        state.last_combat_key = key

        -- Check if defender died from this blow
        pcall(function()
            if not dfhack.units.isAlive(defender) then
                entry.is_lethal = true
            end
        end)
    end)
end

--- Handle report events — capture combat narrative text and chat/conversation reports.
--- Hook: eventful.onReport(report_id)
--- Combat: attaches descriptive text to the most recent pending combat entry.
--- Chat: detects conversation/thought reports and writes them as chat events.
local function on_report(report_id)
    pcall(function()
        -- Find the report object
        local report = nil
        pcall(function()
            -- Reports are in df.global.world.status.reports
            for i = #df.global.world.status.reports - 1, math.max(0, #df.global.world.status.reports - 10), -1 do
                local r = df.global.world.status.reports[i]
                if r and r.id == report_id then
                    report = r
                    break
                end
            end
        end)

        if not report then return end
        if not report.text or report.text == '' then return end

        local text = report.text
        pcall(function() text = dfhack.df2utf(text) end)

        -- Get report type and speaker
        local report_type = -1
        local speaker_id = -1
        pcall(function() report_type = report.type end)
        pcall(function() speaker_id = report.speaker_id end)

        -- === REPORT TYPE ROUTING ===
        -- Full enum: https://github.com/DFHack/df-structures/blob/master/df.g_src.basics.xml

        -- Skip: noise, handled elsewhere, or uninteresting
        local skip_types = {
            [104] = true,   -- CANCEL_JOB
            [236] = true,   -- PROFESSION_CHANGES (handled by polling)
            [237] = true,   -- RECRUIT_PROMOTED (handled by polling)
            [278] = true,   -- SOMEBODY_GROWS_UP (animal growth)
            [282] = true,   -- CITIZEN_BECOMES_SOLDIER (handled by polling)
            [283] = true,   -- CITIZEN_BECOMES_NONSOLDIER (handled by polling)
            [297] = true,   -- SEASON_SPRING (handled by polling)
            [298] = true,   -- SEASON_SUMMER
            [299] = true,   -- SEASON_AUTUMN
            [300] = true,   -- SEASON_WINTER
            [342] = true,   -- EMBARK_MESSAGE
        }
        if skip_types[report_type] then return end

        -- 1. Combat reports (types 6-48, 111-134, 166-167, 239): attach to pending combat
        local is_combat_type = (report_type >= 6 and report_type <= 48)
            or (report_type >= 111 and report_type <= 134)
            or report_type == 166 or report_type == 167
            or report_type == 239 or report_type == 171
        if is_combat_type and state.last_combat_key then
            local entry = state.pending_combat[state.last_combat_key]
            if entry then
                if #entry.report_lines < 50 then
                    table.insert(entry.report_lines, text)
                end
                return
            end
        end

        -- 2. Dramatic events: threats, megabeasts, transformations, discoveries
        local dramatic_types = {
            [1] = 'era_change',
            [2] = 'feature_discovery',
            [3] = 'struck_deep_metal',
            [4] = 'struck_mineral',
            [5] = 'struck_economic_mineral',
            [51] = 'dig_cancel_warm',
            [52] = 'dig_cancel_damp',
            [53] = 'ambush', [54] = 'ambush', [55] = 'ambush', [56] = 'ambush',
            [57] = 'ambush', [58] = 'ambush', [59] = 'ambush', [60] = 'ambush',
            [61] = 'ambush', [62] = 'ambush', [63] = 'ambush', [64] = 'ambush',
            [65] = 'ambush', [66] = 'ambush',
            [82] = 'cave_collapse',
            [93] = 'megabeast_arrival',
            [94] = 'werebeast_arrival',
            [96] = 'berserk_citizen',
            [97] = 'magma_defaces_engraving',
            [98] = 'engraving_melts',
            [100] = 'master_architecture_lost',
            [101] = 'master_construction_lost',
            [108] = 'endgame_event', [109] = 'endgame_event', [110] = 'endgame_event',
            [136] = 'night_attack_start',
            [137] = 'night_attack_end',
            [145] = 'creature_steals_object',
            [147] = 'body_transformation',
            [150] = 'undead_attack',
            [151] = 'citizen_missing',
            [152] = 'pet_missing',
            [154] = 'strange_rain',
            [155] = 'strange_cloud',
            [181] = 'stressed_citizen',
            [182] = 'citizen_lost_to_stress',
            [183] = 'citizen_tantrum',
            [252] = 'citizen_snatched',
            [257] = 'artwork_defaced',
            [285] = 'possessed_tantrum',
            [286] = 'building_toppled_by_ghost',
            [313] = 'building_destroyed',
            [314] = 'deity_curse',
            [348] = 'food_warning',
            [351] = 'deity_pronouncement',
        }
        if dramatic_types[report_type] then
            write_event('report', {
                report_type = dramatic_types[report_type],
                text = text,
                category = 'dramatic',
            })
            return
        end

        -- 3. Social/political events
        local social_types = {
            [153] = 'embrace',
            [176] = 'gain_site_control',
            [178] = 'position_succession',
            [254] = 'land_gains_status',
            [255] = 'land_elevated_status',
            [258] = 'power_learned',
            [266] = 'election_results',
            [284] = 'party_organized',
            [289] = 'marriage',
            [303] = 'research_breakthrough',
            [321] = 'rumor_spread',
            [331] = 'new_guild',
            [332] = 'crime_witness', [333] = 'crime_witness',
            [334] = 'crime_witness', [335] = 'crime_witness',
        }
        if social_types[report_type] then
            write_event('report', {
                report_type = social_types[report_type],
                text = text,
                category = 'social',
            })
            return
        end

        -- 4. Trade/visitor events
        local trade_types = {
            [67] = 'caravan_arrival',
            [68] = 'noble_arrival',
            [79] = 'diplomat_arrival',
            [80] = 'liaison_arrival',
            [81] = 'trade_diplomat_arrival',
            [242] = 'merchants_unloading',
            [245] = 'merchants_leaving_soon',
            [246] = 'merchants_embarked',
            [301] = 'guest_arrival',
            [341] = 'diplomat_left_unhappy',
            [343] = 'first_caravan_arrival',
            [344] = 'monarch_arrival',
            [345] = 'hasty_monarch',
            [346] = 'satisfied_monarch',
        }
        if trade_types[report_type] then
            write_event('report', {
                report_type = trade_types[report_type],
                text = text,
                category = 'trade',
            })
            return
        end

        -- 5. Achievement/mood progression events
        local achievement_types = {
            [86] = 'artifact_created',
            [87] = 'artifact_named',
            [91] = 'mood_building_claimed',
            [92] = 'artifact_begun',
            [99] = 'masterpiece_construction',
            [238] = 'soldier_becomes_master',
            [256] = 'masterpiece_crafted',
            [261] = 'dyed_masterpiece',
            [262] = 'cooked_masterpiece',
            [287] = 'masterful_improvement',
            [288] = 'masterpiece_engraving',
            [315] = 'composition_complete',
        }
        if achievement_types[report_type] then
            write_event('report', {
                report_type = achievement_types[report_type],
                text = text,
                category = 'achievement',
            })
            return
        end

        -- 6. Chat/conversation: speaker_id >= 0 means a dwarf said/thought this.
        --    Type 163 = REGULAR_CONVERSATION, 177 = CONFLICT_CONVERSATION
        if speaker_id >= 0 then
            local speaker = df.unit.find(speaker_id)
            if speaker and is_our_dwarf(speaker) then
                -- Skip if speaker is in active combat (battle cries during fights)
                local in_combat = false
                if state.pending_combat then
                    for key, _ in pairs(state.pending_combat) do
                        if key:match('^' .. tostring(speaker_id) .. ':') or key:match(':' .. tostring(speaker_id) .. '$') then
                            in_combat = true
                            break
                        end
                    end
                end
                if not in_combat then
                    write_event('chat', {
                        unit = serialize_unit(speaker),
                        message = text,
                    })
                end
            end
            return
        end
    end)
end

--- Flush pending combat events that have gone stale (no new blows for 200+ ticks).
local function flush_combat()
    if not state.pending_combat then return end
    local tick = df.global.cur_year_tick
    local stale_keys = {}

    for key, entry in pairs(state.pending_combat) do
        -- Flush if 200+ ticks since last blow (fight is over)
        if tick - entry.last_tick > 200 then
            table.insert(stale_keys, key)

            -- Check if defender is now dead (may have died after last blow callback)
            pcall(function()
                if entry.defender and entry.defender.unit_id then
                    local defender = df.unit.find(entry.defender.unit_id)
                    if defender and not dfhack.units.isAlive(defender) then
                        entry.is_lethal = true
                    end
                end
            end)

            write_event('combat', {
                attacker = entry.attacker,
                defender = entry.defender,
                weapon = entry.weapon,
                blows = entry.blows,
                is_lethal = entry.is_lethal,
                is_siege = state.siege_active or false,
                raw_text = table.concat(entry.report_lines or {}, '\n'),
            })
        end
    end

    for _, key in ipairs(stale_keys) do
        state.pending_combat[key] = nil
    end
end

--- Handle item creation events.
--- Hook: eventful.onItemCreated(item_id)
--- We only care about artifacts (mood-created items), not routine crafts.
local function on_item_created(item_id)
    pcall(function()
        local item = df.item.find(item_id)
        if not item then return end

        -- Check if this item is an artifact
        local dominated = false
        for _, artifact in ipairs(df.global.world.artifacts.all) do
            if artifact.item and artifact.item.id == item_id then
                dominated = true

                local data = {
                    artifact_id = artifact.id,
                    name = '',
                    item_type = '',
                    material = '',
                    creator_unit_id = -1,
                    creator = nil,
                }

                pcall(function()
                    data.name = dfhack.items.getDescription(item, 0, true) or ''
                    data.item_type = df.item_type[item:getType()] or ''
                end)
                pcall(function()
                    local mat_info = dfhack.matinfo.decode(item)
                    if mat_info then data.material = mat_info:toString() end
                end)
                pcall(function()
                    if item.maker and item.maker.unit_id >= 0 then
                        data.creator_unit_id = item.maker.unit_id
                        local creator = df.unit.find(item.maker.unit_id)
                        if creator then data.creator = serialize_unit(creator) end
                    end
                end)
                pcall(function()
                    if artifact.name and artifact.name.has_name then
                        local art_name = dfhack.df2utf(dfhack.translation.translateName(artifact.name, true))
                        if art_name ~= '' then data.name = art_name end
                    end
                end)

                write_event('artifact', data)
                break
            end
        end
    end)
end

--- Handle invasion events.
--- Hook: eventful.onInvasion(invasion_id)
--- Fires instantly when invaders appear — replaces polling for siege start.
local function on_invasion(invasion_id)
    pcall(function()
        state.siege_active = true

        local data = {
            status = 'started',
            invasion_id = invasion_id,
            invader_count = 0,
            invader_race = 'unknown',
            civilization = 'unknown',
        }

        -- Try to get details from the active army controllers
        pcall(function()
            local invaders = {}
            local race_name = ''
            local civ_name = ''
            for _, unit in ipairs(df.global.world.units.active) do
                if dfhack.units.isAlive(unit) and dfhack.units.isInvader(unit) then
                    table.insert(invaders, unit)
                    if race_name == '' then
                        pcall(function()
                            local raw = df.creature_raw.find(unit.race)
                            if raw then race_name = raw.creature_id end
                        end)
                    end
                    if civ_name == '' then
                        pcall(function()
                            if unit.civ_id >= 0 then
                                local civ = df.historical_entity.find(unit.civ_id)
                                if civ then
                                    civ_name = dfhack.df2utf(dfhack.translation.translateName(civ.name, true))
                                end
                            end
                        end)
                    end
                end
            end
            data.invader_count = #invaders
            if race_name ~= '' then data.invader_race = race_name end
            if civ_name ~= '' then data.civilization = civ_name end
        end)

        write_event('siege', data)
    end)
end

--- Handle new unit becoming active on the map.
--- Hook: eventful.onUnitNewActive(unit_id)
--- Detects migrants, visitors, invaders arriving. Filters to only fortress-relevant units.
local function on_unit_new_active(unit_id)
    pcall(function()
        local unit = df.unit.find(unit_id)
        if not unit or not dfhack.units.isAlive(unit) then return end

        local player_race = df.global.plotinfo.race_id

        -- Skip units we already know about
        if state.known_unit_ids[unit_id] then return end

        -- Check if this is a fortress dwarf (migrant)
        if unit.race == player_race and dfhack.units.isFortControlled(unit) then
            state.known_unit_ids[unit_id] = true
            write_event('migrant_arrived', {
                unit = serialize_unit(unit),
            })
            return
        end

        -- Check if this is an invader
        if dfhack.units.isInvader(unit) then
            -- Handled by onInvasion — skip to avoid duplicates
            return
        end
    end)
end

--- Handle syndrome application (werebeast bites, vampire curses, FB syndromes).
--- Hook: eventful.onSyndrome(unit_id, syndrome_id)
if not state.known_syndromes then
    state.known_syndromes = {}  -- "unit_id:syndrome_id" -> true
end

local function on_syndrome(unit_id, syndrome_id)
    pcall(function()
        local unit = df.unit.find(unit_id)
        if not unit then return end

        -- Deduplicate: only report each syndrome once per unit
        local key = tostring(unit_id) .. ':' .. tostring(syndrome_id)
        if state.known_syndromes[key] then return end
        state.known_syndromes[key] = true

        -- Get syndrome details
        local syndrome_name = 'unknown'
        local syndrome_class = ''
        pcall(function()
            local syn = df.syndrome.find(syndrome_id)
            if syn then
                if syn.syn_name and syn.syn_name ~= '' then
                    syndrome_name = syn.syn_name
                end
                -- Check syndrome class flags for narrative interest
                for _, cls in ipairs(syn.syn_class) do
                    if cls and cls.value then
                        syndrome_class = syndrome_class .. cls.value .. ' '
                    end
                end
            end
        end)

        -- Filter: only report interesting syndromes, skip mundane ones
        local player_race = df.global.plotinfo.race_id
        local is_ours = (unit.race == player_race and dfhack.units.isFortControlled(unit))
        if not is_ours then return end

        -- Skip mundane syndromes (alcohol, minor ailments, food effects)
        local boring = {
            inebriation = true,
            drowsiness = true,
            nausea = true,
            fever = true,
            dizziness = true,
            pain = true,
        }
        local lower_name = syndrome_name:lower()
        if boring[lower_name] then return end
        -- Also skip if the name contains common mundane keywords
        if lower_name:match('alcohol') or lower_name:match('beer')
            or lower_name:match('wine') or lower_name:match('rum')
            or lower_name:match('inebriat') then
            return
        end

        write_event('syndrome', {
            unit = serialize_unit(unit),
            syndrome_name = syndrome_name,
            syndrome_class = syndrome_class:match('^%s*(.-)%s*$') or '',
        })
    end)
end

--- Handle inventory changes.
--- Hook: eventful.onInventoryChange(unit_id, item_id, old_item, new_item)
--- Very noisy — only track weapon/armor equip changes for military dwarves.
local function on_inventory_change(unit_id, item_id, old_inv, new_inv)
    pcall(function()
        local unit = df.unit.find(unit_id)
        if not unit then return end

        -- Only track fortress dwarves in military squads
        local player_race = df.global.plotinfo.race_id
        if unit.race ~= player_race or not dfhack.units.isFortControlled(unit) then return end
        if not unit.military.squad_id or unit.military.squad_id < 0 then return end

        -- Determine what changed: equip or unequip, weapon or armor
        local new_mode = new_inv and new_inv.mode or -1
        local old_mode = old_inv and old_inv.mode or -1

        -- Only care about weapon/armor changes (mode 1=Weapon, 5=Strapped)
        -- Skip mode 2 (Worn/clothing) — too noisy
        local dominated = (new_mode == 1 or new_mode == 5 or
                         old_mode == 1 or old_mode == 5)
        if not dominated then return end

        local item = df.item.find(item_id)
        if not item then return end

        local item_desc = ''
        pcall(function() item_desc = dfhack.items.getDescription(item, 0, false) or '' end)

        local action = 'changed'
        if new_mode == 1 or new_mode == 5 then
            action = 'equipped'
        elseif old_mode == 1 or old_mode == 5 then
            action = 'unequipped'
        end

        write_event('equipment_change', {
            unit = serialize_unit(unit),
            item = item_desc,
            action = action,
        })
    end)
end

--- Handle interaction events (magic, FB attacks, necromancy, etc.).
--- Hook: eventful.onInteraction(interaction_name, interaction_token, attacker_id, defender_id, attacker_hf_id, defender_hf_id)
local function on_interaction(interaction_name, interaction_token, attacker_id, defender_id, attacker_hf_id, defender_hf_id)
    pcall(function()
        local attacker = df.unit.find(attacker_id)
        local defender = df.unit.find(defender_id)

        -- Skip if neither unit is valid
        if not attacker and not defender then return end

        local data = {
            interaction_name = interaction_name or 'unknown',
            interaction_token = interaction_token or '',
            attacker = attacker and serialize_unit(attacker) or nil,
            defender = defender and serialize_unit(defender) or nil,
        }

        write_event('interaction', data)
    end)
end

--- Handle unit death events.
--- Hook: eventful.onUnitDeath
--- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html#units-module
local function on_unit_death(unit_id)
    if not event_flags.death then return end

    local unit = df.unit.find(unit_id)
    if not unit then return end

    local unit_age = 0
    pcall(function() unit_age = dfhack.units.getAge(unit) or 0 end)

    local data = {
        victim = serialize_unit(unit),
        cause = 'unknown',
        age = unit_age,
        notable_skills = get_notable_skills(unit),
    }

    if unit.death_info then
        local death = unit.death_info

        -- Try to get the death cause enum
        pcall(function()
            if death.death_cause and death.death_cause ~= -1 then
                local cause_name = df.death_type[death.death_cause]
                if cause_name then
                    -- Convert enum like OLD_AGE, HUNGER, THIRST, MURDERED, DROWNED, etc.
                    data.cause = cause_name:lower():gsub('_', ' ')
                end
            end
        end)

        -- Capture killer if present
        if death.killer and death.killer ~= -1 then
            local killer = df.unit.find(death.killer)
            if killer then
                data.killer = serialize_unit(killer)
                if data.cause == 'unknown' then
                    data.cause = 'combat'
                end
            end
        end
    end

    -- If the dead unit was a pet, capture its owner for narrative context
    pcall(function()
        if unit.relationship_ids and unit.relationship_ids.PetOwner >= 0 then
            local owner = df.unit.find(unit.relationship_ids.PetOwner)
            if owner then
                data.owner = serialize_unit(owner)
            end
        end
    end)

    write_event('death', data)
    state.death_count = (state.death_count or 0) + 1
end

--- Handle building creation events.
--- Hook: eventful.onBuildingCreated
local function on_building_created(building_id)
    if not event_flags.building_created then return end

    local building = df.building.find(building_id)
    if not building then return end

    local ok, data = pcall(function()
        return {
            building_type = df.building_type[building:getType()] or 'unknown',
            name = dfhack.buildings.getName(building) or '',
            location = {
                x = building.centerx,
                y = building.centery,
                z = building.z,
            },
        }
    end)

    if ok then
        write_event('building_created', data)
    end
end

--- Handle job completion events.
--- Only emit events for notable jobs (artifact creation via moods).
--- Hook: eventful.onJobCompleted
local function on_job_completed(job)
    if not event_flags.job_completed then return end
    if not job then return end

    -- Only capture mood-related artifact creation jobs, not routine work.
    -- Mood artifacts are handled via poll_moods mood_completed event instead.
    -- This hook catches the job type for additional context.
    local job_name = ''
    pcall(function() job_name = df.job_type[job.job_type] or '' end)

    -- Filter: only emit for strange mood artifact jobs
    local mood_jobs = {
        StrangeMoodCrafter = true, StrangeMoodJeweller = true,
        StrangeMoodForge = true, StrangeMoodMagma = true,
        StrangeMoodCarpenter = true, StrangeMoodMason = true,
        StrangeMoodBowyer = true, StrangeMoodTanner = true,
        StrangeMoodWeaver = true, StrangeMoodGlassmaker = true,
        StrangeMoodMechanics = true, StrangeMoodBroker = true,
    }
    if not mood_jobs[job_name] then return end

    local ok, data = pcall(function()
        local worker = nil
        if job.general_refs then
            for _, ref in ipairs(job.general_refs) do
                pcall(function()
                    if df.general_ref_unit_workerst:is_instance(ref) then
                        local unit = df.unit.find(ref.unit_id)
                        if unit then worker = serialize_unit(unit) end
                    end
                end)
            end
        end
        return {
            job_type = job_name,
            worker = worker,
        }
    end)

    if ok then
        write_event('job_completed', data)
    end
end

--- Poll for mood events (units entering or completing strange moods).
--- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html#units-module
local function poll_moods()
    if not event_flags.mood then return end

    if not state.prev_moods then state.prev_moods = {} end

    local mood_names = {
        [0] = 'fey',
        [1] = 'secretive',
        [2] = 'possessed',
        [3] = 'macabre',
        [4] = 'fell',
    }

    for _, unit in ipairs(df.global.world.units.active) do
        if is_our_dwarf(unit) then
            local uid = unit.id
            local prev = state.prev_moods[uid]

            if unit.mood >= 0 then
                -- Currently in a mood
                local mood_key = uid .. '_mood_' .. tostring(unit.mood)
                if not state.known_unit_ids[mood_key] then
                    state.known_unit_ids[mood_key] = true
                    state.prev_moods[uid] = unit.mood

                    -- Try to capture claimed materials from the mood job
                    local claimed = {}
                    pcall(function()
                        if unit.job and unit.job.current_job and unit.job.current_job.items then
                            for _, item_ref in ipairs(unit.job.current_job.items) do
                                pcall(function()
                                    if item_ref.item then
                                        local desc = dfhack.items.getDescription(item_ref.item, 0, true)
                                        if desc and desc ~= '' then
                                            table.insert(claimed, desc)
                                        end
                                    end
                                end)
                            end
                        end
                    end)

                    write_event('mood', {
                        unit = serialize_unit(unit),
                        mood_type = mood_names[unit.mood] or 'unknown',
                        claimed_materials = claimed,
                    })
                end
            elseif prev and prev >= 0 then
                -- Was in a mood, now finished (mood == -1)
                -- Artifact creation is captured by onItemCreated hook separately.
                state.prev_moods[uid] = nil

                write_event('mood_completed', {
                    unit = serialize_unit(unit),
                    previous_mood = mood_names[prev] or 'unknown',
                    success = dfhack.units.isAlive(unit),
                })
            end
        end
    end
end

--- Poll for season changes.
local function poll_season()
    if not event_flags.season_change then return end

    local current = get_season(df.global.cur_year_tick)
    if current ~= state.last_season then
        state.last_season = current

        local pop = 0
        for _, unit in ipairs(df.global.world.units.active) do
            if is_our_dwarf(unit) then
                pop = pop + 1
            end
        end

        -- Track peak population
        state.peak_population = math.max(state.peak_population or 0, pop)

        write_event('season_change', {
            new_season = current,
            population = pop,
            fortress_wealth = (function()
                local ok, val = pcall(function()
                    return df.global.plotinfo.tasks.wealth.total
                end)
                return ok and val or 0
            end)(),
            deaths_this_season = state.death_count or 0,
            peak_population = state.peak_population or 0,
        })

        -- Reset death counter for next season
        state.death_count = 0

        -- Save baselines on season change for persistence
        save_baselines()

        -- Auto-snapshot on season change to capture current dwarf state.
        -- Schedule slightly after the season tick to avoid issues with
        -- running scripts from inside a timer callback.
        dfhack.timeout(10, 'ticks', function()
            print('[storyteller] Season changed to ' .. current .. ' — taking automatic snapshot...')
            local ok, err = pcall(function()
                dfhack.run_script('storyteller-begin', '--snapshot-only')
            end)
            if not ok then
                dfhack.printerr('[storyteller] Auto-snapshot failed: ' .. tostring(err))
            end
        end)
    end
end

--- Poll for births (new units appearing in the active list).
local function poll_births()
    if not event_flags.birth then return end

    for _, unit in ipairs(df.global.world.units.active) do
        if is_our_dwarf(unit) and not state.known_unit_ids[unit.id] then
            state.known_unit_ids[unit.id] = true
            local unit_age = 0
            pcall(function() unit_age = dfhack.units.getAge(unit) or 0 end)
            if unit_age == 0 then
                write_event('birth', {
                    child = serialize_unit(unit),
                })
            end
        end
    end
end

--- Poll for changes in dwarf state (positions, professions, squads, stress, migrants).
--- Compares current state to previous snapshot and emits events for differences.
local function poll_changes()
    local player_race = df.global.plotinfo.race_id
    local current_pop = 0

    for _, unit in ipairs(df.global.world.units.active) do
        if not is_our_dwarf(unit) then goto continue end
        current_pop = current_pop + 1
        local uid = unit.id
        local udata = serialize_unit(unit)

        -- Detect profession change (e.g. became militia commander)
        local prof = dfhack.units.getProfessionName(unit)
        if state.prev_professions[uid] and state.prev_professions[uid] ~= prof then
            write_event('profession_change', {
                unit = udata,
                old_profession = state.prev_professions[uid],
                new_profession = prof,
            })
        end
        state.prev_professions[uid] = prof

        -- Detect noble position changes
        pcall(function()
            local positions = dfhack.units.getNoblePositions(unit)
            local pos_names = {}
            if positions then
                for _, pos in ipairs(positions) do
                    pcall(function()
                        local name = pos.position.name[0] or pos.position.name_male[0] or ''
                        if name ~= '' then table.insert(pos_names, name) end
                    end)
                end
            end
            local pos_key = table.concat(pos_names, ',')
            local prev_key = state.prev_nobles[uid] or ''
            if prev_key ~= pos_key and pos_key ~= '' then
                write_event('noble_appointment', {
                    unit = udata,
                    positions = pos_names,
                })
            end
            state.prev_nobles[uid] = pos_key
        end)

        -- Detect military squad changes
        pcall(function()
            local squad_id = unit.military and unit.military.squad_id or -1
            local prev_squad = state.prev_squads[uid] or -1
            if prev_squad ~= squad_id and squad_id >= 0 then
                local squad_name = ''
                pcall(function() squad_name = dfhack.military.getSquadName(squad_id) end)
                write_event('military_change', {
                    unit = udata,
                    squad_name = squad_name,
                    squad_id = squad_id,
                })
            end
            state.prev_squads[uid] = squad_id
        end)

        -- Detect skill level-ups (significant tier changes only)
        pcall(function()
            if not state.prev_skills then state.prev_skills = {} end
            if not state.prev_skills[uid] then state.prev_skills[uid] = {} end

            -- Skill tier names by rating value
            local tier_names = {
                [0] = 'Dabbling', [1] = 'Novice', [2] = 'Adequate',
                [3] = 'Competent', [4] = 'Skilled', [5] = 'Proficient',
                [6] = 'Talented', [7] = 'Adept', [8] = 'Expert',
                [9] = 'Professional', [10] = 'Accomplished', [11] = 'Great',
                [12] = 'Master', [13] = 'High Master', [14] = 'Grand Master',
                [15] = 'Legendary',
            }
            -- Only report these milestone tiers (skip minor gains)
            local milestone_tiers = { [5] = true, [9] = true, [12] = true, [15] = true }

            local soul = unit.status and unit.status.current_soul
            if soul and soul.skills then
                for _, skill in ipairs(soul.skills) do
                    local rating = skill.rating or 0
                    local skill_id = skill.id
                    local prev_rating = state.prev_skills[uid][skill_id] or 0
                    if rating > prev_rating and milestone_tiers[rating] then
                        local skill_name = ''
                        pcall(function()
                            skill_name = df.job_skill.attrs[skill_id].caption or df.job_skill[skill_id] or tostring(skill_id)
                        end)
                        if skill_name == '' then skill_name = tostring(skill_id) end
                        write_event('skill_level_up', {
                            unit = udata,
                            skill = skill_name,
                            new_level = tier_names[rating] or tostring(rating),
                            rating = rating,
                        })
                    end
                    state.prev_skills[uid][skill_id] = rating
                end
            end
        end)

        -- Detect stress level changes (significant shifts only)
        pcall(function()
            local stress = dfhack.units.getStressCategory(unit)
            local prev_stress = state.prev_stress[uid]
            if prev_stress and prev_stress ~= stress then
                local stress_names = {
                    [0] = 'ecstatic', [1] = 'happy', [2] = 'content',
                    [3] = 'fine', [4] = 'stressed', [5] = 'very unhappy',
                    [6] = 'on the verge of a breakdown',
                }
                -- Only report significant changes (more than 1 level shift)
                if math.abs(stress - prev_stress) >= 2 then
                    write_event('stress_change', {
                        unit = udata,
                        old_stress = stress_names[prev_stress] or tostring(prev_stress),
                        new_stress = stress_names[stress] or tostring(stress),
                    })
                end
            end
            state.prev_stress[uid] = stress
        end)

        -- Detect new relationships forming
        pcall(function()
            if not state.prev_relationships then state.prev_relationships = {} end
            if not state.prev_relationships[uid] then state.prev_relationships[uid] = {} end

            if unit.hist_figure_id and unit.hist_figure_id >= 0 then
                local hf = df.historical_figure.find(unit.hist_figure_id)
                if hf and hf.histfig_links then
                    local link_type_names = {
                        histfig_hf_link_spousest = 'spouse',
                        histfig_hf_link_loverst = 'lover',
                        histfig_hf_link_childst = 'child',
                        histfig_hf_link_companionst = 'companion',
                    }
                    for _, link in ipairs(hf.histfig_links) do
                        pcall(function()
                            local target_hf_id = link.target_hf
                            if not target_hf_id or target_hf_id < 0 then return end

                            local class_name = tostring(link._type):match('([%w_]+)>') or ''
                            local rel_type = link_type_names[class_name]
                            if not rel_type then return end -- only track significant relationships

                            local rel_key = tostring(target_hf_id) .. '_' .. rel_type
                            if not state.prev_relationships[uid][rel_key] then
                                state.prev_relationships[uid][rel_key] = true

                                -- Find the target's name
                                local target_name = 'someone'
                                for _, u in ipairs(df.global.world.units.active) do
                                    if u.hist_figure_id == target_hf_id then
                                        target_name = dfhack.units.getReadableName(u)
                                        pcall(function() target_name = dfhack.df2utf(target_name) end)
                                        break
                                    end
                                end

                                write_event('relationship_formed', {
                                    unit = udata,
                                    target_name = target_name,
                                    target_hf_id = target_hf_id,
                                    relationship_type = rel_type,
                                })
                            end
                        end)
                    end
                end
            end
        end)

        -- Detect tantrum/berserk states
        pcall(function()
            if not state.prev_tantrum then state.prev_tantrum = {} end
            local tantrum_state = nil
            -- Check for berserk (mood == -1 doesn't cover this; use flags)
            if unit.flags3 and unit.flags3.scuttle then
                tantrum_state = 'berserk'
            elseif unit.mood == 3 then -- macabre/fell can turn violent
                tantrum_state = 'fell'
            end
            -- Also check counters for tantrum
            if not tantrum_state and unit.counters and unit.counters.soldier_mood > 0 then
                tantrum_state = 'martial_tantrum'
            end
            -- Check stress-related tantrum via very high stress
            if not tantrum_state then
                local stress = dfhack.units.getStressCategory(unit)
                if stress >= 6 and not state.prev_tantrum[uid] then
                    tantrum_state = 'breakdown'
                end
            end
            if tantrum_state and state.prev_tantrum[uid] ~= tantrum_state then
                write_event('tantrum', {
                    unit = udata,
                    tantrum_type = tantrum_state,
                })
            end
            state.prev_tantrum[uid] = tantrum_state
        end)

        -- Track known unit IDs (individual migrant_arrived events handled by onUnitNewActive hook)
        if not state.known_unit_ids[uid] then
            state.known_unit_ids[uid] = true
        end

        ::continue::
    end

    -- Detect population changes (summarize)
    if state.prev_population > 0 and current_pop > state.prev_population then
        local diff = current_pop - state.prev_population
        if diff > 1 then
            write_event('migration_wave', {
                new_arrivals = diff,
                total_population = current_pop,
            })
        end
    end
    state.prev_population = current_pop
end

--- Poll for new noble mandates.
local function poll_mandates()
    if not event_flags.mandate then return end
    pcall(function()
        local mandates = df.global.plotinfo.tasks.mandates
        if not mandates then return end
        for i, mandate in ipairs(mandates) do
            pcall(function()
                local key = tostring(i) .. '_' .. tostring(mandate.mode or 0) .. '_' .. tostring(mandate.item_type or 0)
                if state.prev_mandates[key] then return end
                state.prev_mandates[key] = true

                local data = {
                    mandate_type = 'unknown',
                    item_type = '',
                    material = '',
                    issuer = nil,
                }
                pcall(function()
                    if mandate.mode == 0 then data.mandate_type = 'export_prohibition'
                    elseif mandate.mode == 1 then data.mandate_type = 'production_order'
                    else data.mandate_type = tostring(mandate.mode) end
                end)
                pcall(function()
                    if mandate.item_type >= 0 then
                        data.item_type = df.item_type[mandate.item_type] or tostring(mandate.item_type)
                    end
                end)
                pcall(function()
                    if mandate.mat_type >= 0 then
                        local mat = dfhack.matinfo.decode(mandate.mat_type, mandate.mat_index)
                        if mat then data.material = mat:toString() end
                    end
                end)
                pcall(function()
                    if mandate.unit and mandate.unit.id then
                        data.issuer = serialize_unit(mandate.unit)
                    end
                end)
                write_event('mandate', data)
            end)
        end
    end)
end

--- Incident types that are actual crimes/justice events (not combat or animal kills).
--- DF uses the incident system for all kinds of events; we only want real crimes.
local CRIME_INCIDENT_TYPES = {
    THEFT = true,
    THEFT_FOOD = true,
    THEFT_ITEM = true,
    VANDALISM = true,
    ASSAULT = true,
    MURDER = true,
    KIDNAPPING = true,
    SABOTAGE = true,
    TREASON = true,
    CONSPIRACY = true,
    BRAWL = true,
    HARASSMENT = true,
    ROBBERY = true,
    BREAKING_AND_ENTERING = true,
}

--- Poll for new crime/incident reports.
local function poll_crimes()
    if not event_flags.crime then return end
    pcall(function()
        local incidents = df.global.world.incidents.all
        if not incidents then return end
        for _, incident in ipairs(incidents) do
            pcall(function()
                local key = tostring(incident.id)
                if state.prev_crimes[key] then return end
                state.prev_crimes[key] = true

                -- Get the incident type name
                local type_name = 'unknown'
                pcall(function()
                    if incident.type then
                        type_name = df.incident_type[incident.type] or tostring(incident.type)
                    end
                end)

                -- Skip non-crime incidents (animal kills, combat, etc.)
                if not CRIME_INCIDENT_TYPES[type_name] then return end

                local data = {
                    crime_type = type_name,
                    victim = nil,
                    suspect = nil,
                }
                pcall(function()
                    if incident.victim and incident.victim >= 0 then
                        local victim = df.unit.find(incident.victim)
                        if victim then data.victim = serialize_unit(victim) end
                    end
                end)
                pcall(function()
                    if incident.criminal and incident.criminal >= 0 then
                        local suspect = df.unit.find(incident.criminal)
                        if suspect then data.suspect = serialize_unit(suspect) end
                    end
                end)
                write_event('crime', data)
            end)
        end
    end)
end

--- Poll for caravan/diplomat arrivals.
local function poll_caravans()
    if not event_flags.caravan then return end
    pcall(function()
        for _, unit in ipairs(df.global.world.units.active) do
            pcall(function()
                if not dfhack.units.isAlive(unit) then return end
                local uid = unit.id
                if state.known_caravans[uid] then return end

                local caravan_type = nil
                pcall(function()
                    if unit.flags1.merchant then caravan_type = 'merchant' end
                end)
                pcall(function()
                    if unit.flags1.diplomat then caravan_type = 'diplomat' end
                end)
                if not caravan_type then return end

                state.known_caravans[uid] = true
                local civ_name = ''
                pcall(function()
                    if unit.civ_id >= 0 then
                        local entity = df.historical_entity.find(unit.civ_id)
                        if entity and entity.name then
                            civ_name = dfhack.df2utf(dfhack.translation.translateName(entity.name, true))
                        end
                    end
                end)
                write_event('caravan', {
                    caravan_type = caravan_type,
                    civilization = civ_name,
                    civ_id = unit.civ_id,
                    visitor = serialize_unit(unit),
                })
            end)
        end
    end)
end

--- Poll for siege / invasion events.
--- Poll for siege end only — siege start is handled by onInvasion hook.
local function poll_sieges()
    if not event_flags.siege then return end
    pcall(function()
        if not state.siege_active then return end

        -- Check if all invaders are gone
        local invader_count = 0
        for _, unit in ipairs(df.global.world.units.active) do
            pcall(function()
                if dfhack.units.isAlive(unit) and unit.flags1 and unit.flags1.active_invader then
                    invader_count = invader_count + 1
                end
            end)
        end

        if invader_count == 0 then
            state.siege_active = false
            write_event('siege', {
                status = 'ended',
                invader_count = 0,
                invader_race = '',
                civilization = '',
                civ_id = -1,
            })
        end
    end)
end

--- Lightweight delta snapshot: only fast-changing fields per citizen.
--- Runs every ~2400 ticks (roughly 2 in-game days) to keep the web UI fresh
--- without the cost of a full serialize_unit + pet scan + building loop.
local DELTA_INTERVAL = 24  -- every 24 polls (24 * 100 = 2400 ticks)

local function write_delta_snapshot()
    pcall(function()
        local player_race = df.global.plotinfo.race_id
        local citizens = {}
        for _, unit in ipairs(df.global.world.units.active) do
            if dfhack.units.isAlive(unit) and unit.race == player_race and dfhack.units.isFortControlled(unit) then
                pcall(function()
                    local entry = {
                        unit_id = unit.id,
                        name = safe_unit_name(unit),
                        profession = dfhack.units.getProfessionName(unit),
                        stress_category = dfhack.units.getStressCategory(unit),
                        is_alive = true,
                        current_job = '',
                        mood = -1,
                    }
                    pcall(function()
                        if unit.job and unit.job.current_job then
                            entry.current_job = df.job_type[unit.job.current_job.job_type] or ''
                        end
                    end)
                    pcall(function() entry.mood = unit.mood end)
                    -- Wounds (lightweight — just body part names + permanent flag)
                    local wounds = {}
                    pcall(function()
                        if unit.body and unit.body.wounds then
                            for _, wound in ipairs(unit.body.wounds) do
                                pcall(function()
                                    for _, part in ipairs(wound.parts) do
                                        pcall(function()
                                            local raw = df.creature_raw.find(unit.race)
                                            local bp = raw.caste[unit.caste].body_info.body_parts[part.body_part_id].name_singular[0].value
                                            if bp then
                                                local is_perm = false
                                                pcall(function()
                                                    if (part.flags2 and (part.flags2.severed or part.flags2.missing)) or (wound.age and wound.age > 1000) then
                                                        is_perm = true
                                                    end
                                                end)
                                                table.insert(wounds, { body_part = bp, is_permanent = is_perm })
                                            end
                                        end)
                                    end
                                end)
                            end
                        end
                    end)
                    entry.wounds = wounds
                    table.insert(citizens, entry)
                end)
            end
        end

        local year = df.global.cur_year
        local tick = df.global.cur_year_tick
        local season = get_season(tick)
        local delta = {
            event_type = 'delta_snapshot',
            game_year = year,
            game_tick = tick,
            season = season,
            session_id = fortress_session_id,
            data = { citizens = citizens, population = #citizens },
        }

        local filename = string.format('delta_%d_%06d_%d', year, tick, os.time())
        local tmp_path = output_dir .. filename .. '.tmp'
        local json_path = output_dir .. filename .. '.json'
        local f = io.open(tmp_path, 'w')
        if f then
            f:write(json.encode(delta))
            f:close()
            os.rename(tmp_path, json_path)
        end
    end)
end

--- Main tick handler.
local function on_tick()
    if not state.enabled then return end
    state.poll_count = (state.poll_count or 0) + 1

    local ok, err = pcall(function()
        flush_combat()
        poll_moods()
        poll_season()
        poll_births()
        poll_changes()
        poll_mandates()
        poll_crimes()
        poll_caravans()
        poll_sieges()
    end)

    -- Delta snapshot every DELTA_INTERVAL polls
    if state.poll_count % DELTA_INTERVAL == 0 then
        pcall(write_delta_snapshot)
    end

    if not ok then
        dfhack.printerr('[storyteller] Tick error: ' .. tostring(err))
    end
end

-- ======================= Commands =======================

--- Save baseline state to disk for persistence across DF restarts.
local function save_baselines()
    pcall(function()
        local path = output_dir .. '.baselines.json'
        local data = {
            prev_professions = state.prev_professions or {},
            prev_nobles = state.prev_nobles or {},
            prev_squads = state.prev_squads or {},
            prev_stress = state.prev_stress or {},
            prev_population = state.prev_population or 0,
            last_season = state.last_season or '',
            prev_mandates = state.prev_mandates or {},
            prev_crimes = state.prev_crimes or {},
            peak_population = state.peak_population or 0,
            death_count = state.death_count or 0,
            siege_active = state.siege_active or false,
        }
        -- known_unit_ids keys are numeric but JSON needs string keys
        local known = {}
        for k, v in pairs(state.known_unit_ids or {}) do
            known[tostring(k)] = v
        end
        data.known_unit_ids = known

        local tmp = path .. '.tmp'
        local f = io.open(tmp, 'w')
        if f then
            f:write(json.encode(data))
            f:close()
            os.rename(tmp, path)
        end
    end)
end

--- Load saved baselines from disk if available.
local function load_baselines()
    local path = output_dir .. '.baselines.json'
    local ok, data = pcall(function()
        local f = io.open(path, 'r')
        if not f then return nil end
        local content = f:read('*a')
        f:close()
        return json.decode(content)
    end)
    if ok and data then
        state.prev_professions = data.prev_professions or {}
        state.prev_nobles = data.prev_nobles or {}
        state.prev_squads = data.prev_squads or {}
        state.prev_stress = data.prev_stress or {}
        state.prev_population = data.prev_population or 0
        state.last_season = data.last_season or ''
        state.prev_mandates = data.prev_mandates or {}
        state.prev_crimes = data.prev_crimes or {}
        state.peak_population = data.peak_population or 0
        state.death_count = data.death_count or 0
        state.siege_active = data.siege_active or false
        -- Restore known_unit_ids (keys were stringified for JSON)
        state.known_unit_ids = {}
        for k, v in pairs(data.known_unit_ids or {}) do
            local num = tonumber(k)
            if num then state.known_unit_ids[num] = v
            else state.known_unit_ids[k] = v end
        end
        return true
    end
    return false
end

local function start()
    if state.enabled then
        print('[storyteller] Already running.')
        return
    end

    ensure_output_dir()

    -- Try to load saved baselines first; if missing, seed from scratch.
    if load_baselines() then
        print('[storyteller] Restored baselines from disk')
    else
        state.known_unit_ids = {}
        state.prev_professions = {}
        state.prev_nobles = {}
        state.prev_squads = {}
        state.prev_stress = {}
        state.prev_population = 0
    end

    local player_race = df.global.plotinfo.race_id
    local pop = 0
    for _, unit in ipairs(df.global.world.units.active) do
        if dfhack.units.isAlive(unit) and unit.race == player_race and dfhack.units.isFortControlled(unit) then
            local uid = unit.id
            state.known_unit_ids[uid] = true
            pop = pop + 1

            -- Seed profession baseline
            state.prev_professions[uid] = dfhack.units.getProfessionName(unit)

            -- Seed noble positions
            pcall(function()
                local positions = dfhack.units.getNoblePositions(unit)
                local names = {}
                if positions then
                    for _, pos in ipairs(positions) do
                        pcall(function()
                            local n = pos.position.name[0] or pos.position.name_male[0] or ''
                            if n ~= '' then table.insert(names, n) end
                        end)
                    end
                end
                state.prev_nobles[uid] = table.concat(names, ',')
            end)

            -- Seed military
            pcall(function()
                state.prev_squads[uid] = unit.military and unit.military.squad_id or -1
            end)

            -- Seed stress
            pcall(function()
                state.prev_stress[uid] = dfhack.units.getStressCategory(unit)
            end)

            -- Seed skills so existing skill levels don't trigger level-up events
            pcall(function()
                if not state.prev_skills then state.prev_skills = {} end
                state.prev_skills[uid] = {}
                local soul = unit.status and unit.status.current_soul
                if soul and soul.skills then
                    for _, skill in ipairs(soul.skills) do
                        state.prev_skills[uid][skill.id] = skill.rating or 0
                    end
                end
            end)
        end
    end
    state.prev_population = pop

    state.last_season = get_season(df.global.cur_year_tick)
    print(string.format('[storyteller] Baseline captured: %d dwarves tracked', pop))

    -- Auto-snapshot on start so web UI has data immediately
    dfhack.timeout(20, 'ticks', function()
        print('[storyteller] Taking initial snapshot...')
        pcall(function()
            dfhack.run_script('storyteller-begin', '--snapshot-only')
        end)
    end)

    -- Register event hooks
    -- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html#eventful
    -- Register event hooks and enable them via EventManager.
    -- enableEvent(eventType, frequency) must be called for hooks to fire.
    -- eventType IDs: UNIT_DEATH=5, JOB_COMPLETED=3, BUILDING=7, UNIT_ATTACK=13,
    --   REPORT=12, ITEM_CREATED=6, INVASION=10, UNIT_NEW_ACTIVE=4,
    --   SYNDROME=9, INVENTORY_CHANGE=11, INTERACTION=15
    -- Frequency 0 = every tick (immediate).
    eventful.enableEvent(eventful.eventType.UNIT_DEATH, 0)
    eventful.enableEvent(eventful.eventType.JOB_COMPLETED, 0)
    eventful.enableEvent(eventful.eventType.BUILDING, 0)
    eventful.enableEvent(eventful.eventType.UNIT_ATTACK, 0)
    eventful.enableEvent(eventful.eventType.REPORT, 0)
    eventful.enableEvent(eventful.eventType.ITEM_CREATED, 0)
    eventful.enableEvent(eventful.eventType.INVASION, 0)
    eventful.enableEvent(eventful.eventType.UNIT_NEW_ACTIVE, 0)
    eventful.enableEvent(eventful.eventType.SYNDROME, 0)
    eventful.enableEvent(eventful.eventType.INVENTORY_CHANGE, 0)
    eventful.enableEvent(eventful.eventType.INTERACTION, 0)

    eventful.onUnitDeath.storyteller = on_unit_death
    eventful.onBuildingCreatedDestroyed.storyteller = on_building_created
    eventful.onJobCompleted.storyteller = on_job_completed
    eventful.onUnitAttack.storyteller = on_unit_attack
    eventful.onReport.storyteller = on_report
    eventful.onItemCreated.storyteller = on_item_created
    eventful.onInvasion.storyteller = on_invasion
    eventful.onUnitNewActive.storyteller = on_unit_new_active
    eventful.onSyndrome.storyteller = on_syndrome
    eventful.onInventoryChange.storyteller = on_inventory_change
    eventful.onInteraction.storyteller = on_interaction

    -- Use dfhack.timeout for periodic polling (moods, births, seasons).
    -- The eventful plugin does not support TICK subscriptions.
    local function poll_loop()
        if not state.enabled then return end
        on_tick()
        dfhack.timeout(poll_interval_ticks, 'ticks', poll_loop)
    end
    dfhack.timeout(poll_interval_ticks, 'ticks', poll_loop)

    state.enabled = true
    print('[storyteller] Event monitoring started. Output: ' .. output_dir)
end

local function stop()
    if not state.enabled then
        print('[storyteller] Not running.')
        return
    end

    eventful.onUnitDeath.storyteller = nil
    eventful.onBuildingCreatedDestroyed.storyteller = nil
    eventful.onJobCompleted.storyteller = nil
    eventful.onUnitAttack.storyteller = nil
    eventful.onReport.storyteller = nil
    eventful.onItemCreated.storyteller = nil
    eventful.onInvasion.storyteller = nil
    eventful.onUnitNewActive.storyteller = nil
    eventful.onSyndrome.storyteller = nil
    eventful.onInventoryChange.storyteller = nil
    eventful.onInteraction.storyteller = nil

    -- Flush any remaining combat events before stopping
    pcall(flush_combat)

    save_baselines()
    state.enabled = false
    print('[storyteller] Event monitoring stopped. Baselines saved.')
end

local function status()
    if state.enabled then
        print('[storyteller] Running. Events written: ' .. state.sequence)
        print('[storyteller] Poll ticks: ' .. tostring(state.poll_count or 0))
        print('[storyteller] Output directory: ' .. output_dir)
        print('[storyteller] Tracking ' .. tostring(state.prev_population) .. ' dwarves')
        print('[storyteller] Last season: ' .. tostring(state.last_season))
        print('[storyteller] Current season: ' .. get_season(df.global.cur_year_tick))
    else
        print('[storyteller] Not running.')
    end
end

--- Manually run one poll cycle and report what happened (for debugging).
local function debug_poll()
    print('[storyteller] === Debug Poll ===')
    print('[storyteller] Output dir: ' .. output_dir)
    print('[storyteller] Enabled: ' .. tostring(state.enabled))
    print('[storyteller] Sequence (events written): ' .. tostring(state.sequence))
    print('[storyteller] Poll count (ticks fired): ' .. tostring(state.poll_count or 0))
    print('[storyteller] Prev population: ' .. tostring(state.prev_population))

    -- Show season state
    local current_season = get_season(df.global.cur_year_tick)
    print('[storyteller] Current season: ' .. current_season .. ' | Last recorded: ' .. tostring(state.last_season))
    print('[storyteller] Year: ' .. tostring(df.global.cur_year) .. ' | Tick: ' .. tostring(df.global.cur_year_tick))

    -- Check if poll loop is alive (poll_count should increase over time)
    if (state.poll_count or 0) == 0 and state.enabled then
        print('[storyteller] WARNING: Poll loop appears dead (0 ticks fired). Restarting...')
        local function poll_loop()
            if not state.enabled then return end
            on_tick()
            dfhack.timeout(poll_interval_ticks, 'ticks', poll_loop)
        end
        dfhack.timeout(poll_interval_ticks, 'ticks', poll_loop)
        print('[storyteller] Poll loop restarted.')
    end

    local before = state.sequence

    -- Run full poll cycle (same as on_tick)
    local ok, err = pcall(function()
        poll_moods()
        poll_season()
        poll_births()
        poll_changes()
    end)
    if not ok then
        print('[storyteller] Poll ERROR: ' .. tostring(err))
    end
    local after = state.sequence
    print('[storyteller] Events written this cycle: ' .. (after - before))

    -- Show current state of tracked dwarves
    local player_race = df.global.plotinfo.race_id
    for _, unit in ipairs(df.global.world.units.active) do
        if dfhack.units.isAlive(unit) and unit.race == player_race then
            local uid = unit.id
            local name = dfhack.units.getReadableName(unit) or '?'
            local prof = dfhack.units.getProfessionName(unit) or '?'
            local prev_prof = state.prev_professions[uid] or '(no baseline)'

            local squad = -1
            pcall(function() squad = unit.military and unit.military.squad_id or -1 end)
            local prev_squad = state.prev_squads[uid] or -1

            local changed = ''
            if prev_prof ~= prof then changed = changed .. ' PROF_CHANGED' end
            if prev_squad ~= squad then changed = changed .. ' SQUAD_CHANGED' end

            print(string.format('  %s: prof="%s" (prev="%s") squad=%d (prev=%d)%s',
                name, prof, prev_prof, squad, prev_squad, changed))
        end
    end
end

-- Command dispatch
local args = { ... }
local command = args[1] or 'start'

if command == 'start' then
    start()
elseif command == 'stop' then
    stop()
elseif command == 'status' then
    status()
elseif command == 'debug' then
    debug_poll()
else
    print('Usage: storyteller-events [start|stop|status|debug]')
end
