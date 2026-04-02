-- Debug: identify the ACTUAL tissue type for each tissue_length index
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local player_race = df.global.plotinfo.race_id
for _, unit in ipairs(df.global.world.units.active) do
    if unit.race == player_race and dfhack.units.isCitizen(unit) then
        local name = dfhack.df2utf(dfhack.units.getReadableName(unit))
        local sex = unit.sex == 0 and 'F' or 'M'
        if sex ~= 'M' then goto continue end

        print('=== ' .. name .. ' ===')
        local raw = df.creature_raw.find(unit.race)
        local caste = raw.caste[unit.caste]
        local bpa = caste.bp_appearance
        local body = caste.body_info

        -- For each styled tissue (style_part_idx entry), resolve the tissue type
        for i = 0, #bpa.style_part_idx - 1 do
            local part_idx = bpa.style_part_idx[i]
            local layer_idx = bpa.style_layer_idx[i]
            local bp = body.body_parts[part_idx]
            local part_cat = bp.category
            local part_token = bp.token

            -- Get the tissue template/type for this layer
            local tissue_name = '?'
            pcall(function()
                local layer = bp.layers[layer_idx]
                -- layer has tissue_id which references a tissue template
                local tissue_id = layer.tissue_id
                local tissue = caste.tissue[tissue_id]
                tissue_name = tissue.tissue_name_singular
                if tissue_name == '' then
                    tissue_name = tissue.tissue_material_str[0] or '?'
                end
            end)

            -- Also try getting the layer's tissue template name
            local template_name = '?'
            pcall(function()
                local layer = bp.layers[layer_idx]
                template_name = tostring(layer.layer_name)
            end)

            local tl_val = -30000
            local ts_val = -1
            pcall(function() tl_val = unit.appearance.tissue_length[i] end)
            pcall(function() ts_val = unit.appearance.tissue_style[i] end)

            local style_name = ''
            if ts_val == 0 then style_name = 'NEATLY_COMBED'
            elseif ts_val == 1 then style_name = 'BRAIDED'
            elseif ts_val == 2 then style_name = 'DOUBLE_BRAIDS'
            elseif ts_val == 3 then style_name = 'PONY_TAIL'
            elseif ts_val == 4 then style_name = 'CLEAN_SHAVEN'
            elseif ts_val == -1 then style_name = 'N/A'
            end

            if tl_val > 0 or ts_val >= 0 then
                print('  [' .. i .. '] part=' .. part_token .. '(' .. part_cat .. ') layer=' .. layer_idx .. ' tissue=' .. tissue_name .. ' template=' .. template_name .. ' len=' .. tl_val .. ' style=' .. style_name)
            end
        end
        print()
        break  -- first male only
        ::continue::
    end
end
print('Done.')
