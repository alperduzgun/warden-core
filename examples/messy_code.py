
def process_data(data):
    result = []
    if data:
        if len(data) > 0:
            for item in data:
                if item.get('active'):
                    if item.get('value') is not None:
                        if item.get('value') > 10:
                            temp_val = item['value'] * 2
                            result.append(temp_val)
                        else:
                            pass
    return result
