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

local eventful = require('plugins.eventful')
local json = require('json')

-- ======================= Config =======================
-- Per-world subfolder so multiple worlds don't mix data.
-- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html
local world_folder = dfhack.world.ReadWorldFolder()
local output_dir = dfhack.getDFPath() .. '/storyteller_events/' .. world_folder .. '/'
local poll_interval_ticks = 100

-- Read fortress session ID (written by storyteller-begin) to tag events
local fortress_session_id = ''
pcall(function()
    local f = io.open(output_dir .. '.session_id', 'r')
    if f then
        fortress_session_id = f:read('*a'):match('^%s*(.-)%s*$') or ''
        f:close()
    end
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

    local event = {
        event_type = event_type,
        game_year = year,
        game_tick = tick,
        season = season,
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
        if death.killer then
            local killer = df.unit.find(death.killer)
            if killer then
                data.killer = serialize_unit(killer)
                data.cause = 'combat'
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

--- Handle job completion events (especially artifact creation).
--- Hook: eventful.onJobCompleted
local function on_job_completed(job)
    if not event_flags.job_completed then return end
    if not job then return end

    local ok, data = pcall(function()
        return {
            job_type = df.job_type[job.job_type] or 'unknown',
            result = '',
        }
    end)

    if ok then
        write_event('job_completed', data)
    end
end

--- Poll for mood events (units entering strange moods).
--- Ref: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html#units-module
local function poll_moods()
    if not event_flags.mood then return end

    for _, unit in ipairs(df.global.world.units.active) do
        if is_our_dwarf(unit) and unit.mood >= 0 then
            local mood_key = unit.id .. '_mood_' .. tostring(unit.mood)
            if not state.known_unit_ids[mood_key] then
                state.known_unit_ids[mood_key] = true

                local mood_names = {
                    [0] = 'fey',
                    [1] = 'secretive',
                    [2] = 'possessed',
                    [3] = 'macabre',
                    [4] = 'fell',
                }

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

        state.death_count = 0

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

        -- Detect new arrivals (migrants) — units we haven't seen before who aren't babies.
        -- Only fire after baseline is established (prev_population > 0) to avoid
        -- false positives for existing dwarves on first poll.
        if not state.known_unit_ids[uid] then
            state.known_unit_ids[uid] = true
            if state.prev_population > 0 then
                local unit_age = 0
                pcall(function() unit_age = dfhack.units.getAge(unit) or 0 end)
                if unit_age > 1 then
                    write_event('migrant_arrived', {
                        unit = udata,
                    })
                end
            end
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
                local data = {
                    crime_type = 'unknown',
                    victim = nil,
                    suspect = nil,
                }
                pcall(function()
                    if incident.type then
                        data.crime_type = df.incident_type[incident.type] or tostring(incident.type)
                    end
                end)
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
local function poll_sieges()
    if not event_flags.siege then return end
    pcall(function()
        local invader_count = 0
        local invader_race = ''
        local invader_civ = ''
        local invader_civ_id = -1
        for _, unit in ipairs(df.global.world.units.active) do
            pcall(function()
                if dfhack.units.isAlive(unit) and unit.flags1 and unit.flags1.active_invader then
                    invader_count = invader_count + 1
                    if invader_race == '' then
                        pcall(function()
                            invader_race = df.creature_raw.find(unit.race).creature_id
                        end)
                        pcall(function()
                            if unit.civ_id >= 0 then
                                invader_civ_id = unit.civ_id
                                local entity = df.historical_entity.find(unit.civ_id)
                                if entity and entity.name then
                                    invader_civ = dfhack.df2utf(dfhack.translation.translateName(entity.name, true))
                                end
                            end
                        end)
                    end
                end
            end)
        end
        local was_active = state.siege_active or false
        if invader_count > 0 and not was_active then
            state.siege_active = true
            write_event('siege', {
                status = 'started',
                invader_count = invader_count,
                invader_race = invader_race,
                civilization = invader_civ,
                civ_id = invader_civ_id,
            })
        elseif invader_count == 0 and was_active then
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
                        happiness = 0,
                        is_alive = true,
                        current_job = '',
                        mood = -1,
                    }
                    pcall(function() entry.happiness = dfhack.units.getHappiness(unit) or 0 end)
                    pcall(function()
                        if unit.job and unit.job.current_job then
                            entry.current_job = df.job_type[unit.job.current_job.job_type] or ''
                        end
                    end)
                    pcall(function() entry.mood = unit.mood end)
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

local function start()
    if state.enabled then
        print('[storyteller] Already running.')
        return
    end

    ensure_output_dir()

    -- Seed baseline state so we can detect future changes.
    -- Without this, the first poll would have nothing to compare against.
    state.known_unit_ids = {}
    state.prev_professions = {}
    state.prev_nobles = {}
    state.prev_squads = {}
    state.prev_stress = {}
    state.prev_population = 0

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
    -- Available events (from eventful.cpp): onUnitDeath, onJobCompleted,
    -- onBuildingCreatedDestroyed, onReport, onUnitAttack, etc.
    eventful.onUnitDeath.storyteller = on_unit_death
    eventful.onBuildingCreatedDestroyed.storyteller = on_building_created
    eventful.onJobCompleted.storyteller = on_job_completed

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

    state.enabled = false
    print('[storyteller] Event monitoring stopped.')
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
