-- Debug: show ALL DENSE modifiers on HEAD with their tissue template names
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local player_race = df.global.plotinfo.race_id
for _, unit in ipairs(df.global.world.units.active) do
    if unit.race == player_race and dfhack.units.isCitizen(unit) then
        local name = dfhack.df2utf(dfhack.units.getReadableName(unit))
        if not string.find(name, 'Mebzuth') then goto continue end

        print('=== ' .. name .. ' ===')
        local raw = df.creature_raw.find(unit.race)
        local caste = raw.caste[unit.caste]
        local bpa = caste.bp_appearance
        local body = caste.body_info

        -- Show all tissue layers on HEAD with their template names
        print('--- HEAD tissue layers ---')
        local head_bp = body.body_parts[3]
        for i = 0, #head_bp.layers - 1 do
            local layer = head_bp.layers[i]
            local tmpl = '?'
            pcall(function() tmpl = tostring(layer.layer_name) end)
            print('  layer[' .. i .. '] = ' .. tmpl)
        end

        -- Show all DENSE bp_modifiers on HEAD with layer_idx
        print('')
        print('--- DENSE modifiers on HEAD ---')
        for i = 0, #unit.appearance.bp_modifiers - 1 do
            pcall(function()
                local mod_idx = bpa.modifier_idx[i]
                local part_idx = bpa.part_idx[i]
                local layer_idx = bpa.layer_idx[i]
                local mod_def = bpa.modifiers[mod_idx]
                local type_int = mod_def.modifier.type
                local part_cat = string.upper(body.body_parts[part_idx].category)
                if type_int == 10 and part_cat == 'HEAD' then -- DENSE
                    local tmpl = '?'
                    pcall(function()
                        tmpl = tostring(body.body_parts[part_idx].layers[layer_idx].layer_name)
                    end)
                    print('  bp_mod[' .. i .. '] DENSE layer=' .. layer_idx .. ' template=' .. tmpl .. ' value=' .. unit.appearance.bp_modifiers[i])
                end
            end)
        end

        break
        ::continue::
    end
end
print('Done.')
