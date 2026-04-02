-- Debug: dump color modifiers for ALL citizens
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local player_race = df.global.plotinfo.race_id
for _, unit in ipairs(df.global.world.units.active) do
    if unit.race == player_race and dfhack.units.isCitizen(unit) then
        local name = dfhack.df2utf(dfhack.units.getReadableName(unit))
        local raw = df.creature_raw.find(unit.race)
        local caste = raw.caste[unit.caste]

        local line = name .. ': '
        for i, cm in ipairs(caste.color_modifiers) do
            local color_idx = unit.appearance.colors[i]
            local color_name = '?'
            pcall(function()
                if cm.pattern_index and color_idx < #cm.pattern_index then
                    local pattern_id = cm.pattern_index[color_idx]
                    if pattern_id then
                        local pattern = df.descriptor_pattern.find(pattern_id)
                        if pattern and pattern.colors and #pattern.colors > 0 then
                            local color = df.descriptor_color.find(pattern.colors[0])
                            if color then color_name = color.id or '?' end
                        end
                    end
                end
            end)
            local part_count = 0
            pcall(function() part_count = #cm.body_part_id end)
            line = line .. '[' .. i .. ']' .. color_name .. '(' .. part_count .. ') '
        end
        print(line)
    end
end
print('Done.')
