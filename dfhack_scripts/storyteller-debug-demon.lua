-- Debug: try to resolve pcg_layering to tile names via DFHack internals
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

-- Try to find a global pcg registry
print('=== Searching for pcg/tile_graphics resolution ===')

-- Check world.raws.graphics structure
pcall(function()
    local g = df.global.world.raws.graphics
    print('world.raws.graphics type: ' .. tostring(g._type))
    local fields = {}
    for k, v in pairs(g._type._fields) do
        table.insert(fields, k)
    end
    table.sort(fields)
    print('fields: ' .. table.concat(fields, ', '))

    -- Check each field for arrays that might be the pcg registry
    for _, fname in ipairs(fields) do
        pcall(function()
            local val = g[fname]
            if type(val) == 'userdata' then
                pcall(function()
                    local count = #val
                    if count > 100 then
                        print('  ' .. fname .. ': ' .. count .. ' entries')
                        -- Check first entry type
                        pcall(function()
                            local first = val[0]
                            print('    [0] type: ' .. tostring(first._type))
                            local efields = {}
                            for k, v in pairs(first._type._fields) do
                                table.insert(efields, k)
                            end
                            table.sort(efields)
                            print('    [0] fields: ' .. table.concat(efields, ', '))
                            -- Show a few values
                            for _, ef in ipairs(efields) do
                                pcall(function()
                                    local ev = first[ef]
                                    if type(ev) == 'number' then
                                        print('    [0].' .. ef .. ' = ' .. ev)
                                    elseif type(ev) == 'string' and ev ~= '' then
                                        print('    [0].' .. ef .. ' = "' .. ev .. '"')
                                    end
                                end)
                            end
                        end)

                        -- Check entry at pcg=17 (should be BEAST_WORM_LONG)
                        pcall(function()
                            local entry = val[17]
                            local info = '    [17]'
                            pcall(function() info = info .. ' token="' .. entry.token .. '"' end)
                            pcall(function() info = info .. ' name="' .. entry.name .. '"' end)
                            pcall(function() info = info .. ' id=' .. entry.id end)
                            print(info)
                        end)

                        -- Check entry at pcg=1144
                        if count > 1144 then
                            pcall(function()
                                local entry = val[1144]
                                local info = '    [1144]'
                                pcall(function() info = info .. ' token="' .. entry.token .. '"' end)
                                pcall(function() info = info .. ' name="' .. entry.name .. '"' end)
                                pcall(function() info = info .. ' id=' .. entry.id end)
                                print(info)
                            end)
                        end
                    end
                end)
            end
        end)
    end
end)

print('Done.')
