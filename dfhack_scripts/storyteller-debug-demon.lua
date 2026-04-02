-- Debug: dump all graphics_layer fields and resolve pcg_layering
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local found = false
for _, unit in ipairs(df.global.world.units.active) do
    if found then goto done end
    pcall(function()
        local raw = df.creature_raw.find(unit.race)
        if not raw or not raw.flags.GENERATED then return end
        found = true

        print('=== ' .. raw.creature_id .. ' ===')

        -- Dump ALL fields of creature_graphics_layerst
        local gls = raw.graphics.graphics_layer_set
        local entry = gls[0]
        local layers = entry.graphics_layer

        -- Get all field names on a layer
        local layer_fields = {}
        pcall(function()
            for k, v in pairs(layers[0]._type._fields) do
                table.insert(layer_fields, k)
            end
        end)
        table.sort(layer_fields)
        print('layer fields: ' .. table.concat(layer_fields, ', '))
        print('')

        -- Dump all 11 layers
        for i = 0, #layers - 1 do
            local l = layers[i]
            local info = 'layer[' .. i .. ']:'
            for _, fname in ipairs(layer_fields) do
                pcall(function()
                    local val = l[fname]
                    if type(val) == 'number' and val ~= -1 and val ~= 0 then
                        info = info .. ' ' .. fname .. '=' .. val
                    elseif type(val) == 'string' and val ~= '' then
                        info = info .. ' ' .. fname .. '="' .. val .. '"'
                    elseif type(val) == 'userdata' then
                        pcall(function()
                            local count = #val
                            if count > 0 then
                                info = info .. ' ' .. fname .. '[' .. count .. ']'
                            end
                        end)
                    end
                end)
            end
            print(info)
        end

        -- Try to find what pcg_layering maps to
        -- Check if there's a global tile graphics rectangle list
        print('')
        print('Resolving pcg_layering:')
        pcall(function()
            -- Check world.raws for tile graphics
            local tgr = df.global.world.raws.graphics.tile_page_rectangles
            if tgr then
                print('  tile_page_rectangles count: ' .. #tgr)
                -- Check if pcg_layering indexes into this
                for i = 0, #layers - 1 do
                    local pcg = layers[i].pcg_layering
                    if pcg >= 0 and pcg < #tgr then
                        local rect = tgr[pcg]
                        local rinfo = '  pcg ' .. pcg .. ' -> '
                        pcall(function()
                            rinfo = rinfo .. 'type=' .. tostring(rect._type)
                            local rfields = {}
                            for k,v in pairs(rect._type._fields) do table.insert(rfields, k) end
                            table.sort(rfields)
                            for _, rf in ipairs(rfields) do
                                pcall(function()
                                    local rv = rect[rf]
                                    if type(rv) == 'number' then
                                        rinfo = rinfo .. ' ' .. rf .. '=' .. rv
                                    elseif type(rv) == 'string' and rv ~= '' then
                                        rinfo = rinfo .. ' ' .. rf .. '="' .. rv .. '"'
                                    end
                                end)
                            end
                        end)
                        print(rinfo)
                    end
                end
            end
        end)

        -- Also try raw.graphics tile references
        print('')
        print('tile_color:')
        pcall(function()
            print('  fg=' .. raw.tile_color[0] .. ' bg=' .. raw.tile_color[1] .. ' bright=' .. raw.tile_color[2])
        end)
    end)
end
::done::
print('Done.')
