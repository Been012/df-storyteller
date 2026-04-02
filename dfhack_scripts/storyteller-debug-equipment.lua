-- Debug: check ALL dye_profiles (colorationst AND threadst) for undyed items
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local player_race = df.global.plotinfo.race_id
for _, unit in ipairs(df.global.world.units.active) do
    if unit.race == player_race and dfhack.units.isCitizen(unit) then
        local name = dfhack.df2utf(dfhack.units.getReadableName(unit))
        for _, inv in ipairs(unit.inventory) do
            if inv.mode == 2 then
                local item = inv.item
                local item_type = tostring(df.item_type[item:getType()])
                if item_type ~= 'ARMOR' and item_type ~= 'HELM' then goto continue end
                local desc = dfhack.items.getDescription(item, 0, true)
                local quality = 0
                pcall(function() quality = item.quality end)

                local colors_found = {}
                if item.improvements then
                    for j, imp in ipairs(item.improvements) do
                        pcall(function()
                            -- colorationst dye_profile
                            if imp.dye_profile and imp.dye_profile.color_index >= 0 then
                                local c = df.descriptor_color.find(imp.dye_profile.color_index)
                                if c then table.insert(colors_found, 'coloration:' .. c.id) end
                            end
                        end)
                        pcall(function()
                            -- threadst dye sub-object's profile
                            if imp.dye and imp.dye_profile and imp.dye_profile.color_index >= 0 then
                                local c = df.descriptor_color.find(imp.dye_profile.color_index)
                                if c then table.insert(colors_found, 'thread_dye:' .. c.id) end
                            end
                        end)
                    end
                end

                local base = '?'
                pcall(function()
                    local mi = dfhack.matinfo.decode(item)
                    if mi and mi.material then
                        local cid = mi.material.state_color.Solid
                        if cid >= 0 then base = df.descriptor_color.find(cid).id end
                    end
                end)

                print(name:sub(1,20) .. ': ' .. desc .. ' q=' .. quality .. ' base=' .. base .. ' dye=' .. (#colors_found > 0 and table.concat(colors_found, ',') or 'NONE'))
                ::continue::
            end
        end
    end
end
print('Done.')
