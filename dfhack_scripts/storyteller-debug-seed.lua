-- Debug: dump appearance genes for correlation analysis
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local player_race = df.global.plotinfo.race_id
for _, unit in ipairs(df.global.world.units.active) do
    if unit.race == player_race and dfhack.units.isCitizen(unit) then
        local name = dfhack.df2utf(dfhack.units.getReadableName(unit))
        local uid = unit.id

        local genes = {}
        pcall(function()
            for i = 0, #unit.appearance.genes.appearance - 1 do
                table.insert(genes, tostring(unit.appearance.genes.appearance[i]))
            end
        end)

        print(uid .. '|' .. name:sub(1, 15) .. '|' .. unit.birth_time .. '|' .. table.concat(genes, ','))
    end
end
print('Done.')
