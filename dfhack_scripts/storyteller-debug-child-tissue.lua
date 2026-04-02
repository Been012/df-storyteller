-- Debug: check tissue layout for children vs adults
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local player_race = df.global.plotinfo.race_id
for _, unit in ipairs(df.global.world.units.active) do
    if unit.race == player_race and dfhack.units.isCitizen(unit) then
        local age = dfhack.units.getAge(unit)
        local name = dfhack.df2utf(dfhack.units.getReadableName(unit))
        local sex = unit.sex == 0 and 'F' or 'M'

        -- Show both a child and an adult of same sex for comparison
        if age < 12 or (sex == 'F' and age > 20 and age < 50) then
            print('=== ' .. name:sub(1,30) .. ' (' .. sex .. ', age ' .. string.format('%.0f', age) .. ') ===')

            local raw = df.creature_raw.find(unit.race)
            local caste = raw.caste[unit.caste]
            local bpa = caste.bp_appearance
            local body = caste.body_info

            -- Show tissue template for each tissue_length index
            local tl = unit.appearance.tissue_length
            local ts = unit.appearance.tissue_style
            local count = #tl
            print('  tissue count: ' .. count)

            for i = 0, count - 1 do
                local part_idx = bpa.style_part_idx[i]
                local layer_idx = bpa.style_layer_idx[i]
                local bp = body.body_parts[part_idx]
                local tmpl = '?'
                pcall(function() tmpl = tostring(bp.layers[layer_idx].layer_name) end)
                local len = tl[i]
                local style = ts[i]
                if len > 0 or style >= 0 then
                    print('  [' .. i .. '] ' .. tmpl .. ' len=' .. len .. ' style=' .. style)
                end
            end
            print()
        end
    end
end
print('Done.')
