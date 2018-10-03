import ckan.plugins as p
import ckan.plugins.toolkit as tk

from ckan.plugins.toolkit import Invalid

def validate_select(value):
    if value == '0':
	raise Invalid("Select a value")
    return value



class MyIDatasetFormPlugin(p.SingletonPlugin, tk.DefaultDatasetForm):
    p.implements(p.IDatasetForm)
    p.implements(p.IConfigurer)

    def _modify_package_schema(self, schema):
        schema.update({
            'source': [tk.get_validator('ignore_missing'),validate_select,tk.get_converter('convert_to_extras')]
        })
        schema.update({
            'scenario_id': [tk.get_validator('ignore_missing'),tk.get_converter('convert_to_extras')]
        })
        schema.update({
            'reliability_source': [tk.get_validator('ignore_missing'),validate_select,tk.get_converter('convert_to_extras')]
        })
        schema.update({
            'application_id': [tk.get_validator('ignore_missing'),tk.get_converter('convert_to_extras')]
        })
        schema.update({
            'ex_license': [tk.get_validator('ignore_missing'),validate_select,tk.get_converter('convert_to_extras')]
        })
        return schema

    def create_package_schema(self):
        schema = super(MyIDatasetFormPlugin, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self):
        schema = super(MyIDatasetFormPlugin, self).update_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def show_package_schema(self):
        schema = super(MyIDatasetFormPlugin, self).show_package_schema()
        schema.update({
            'source': [tk.get_converter('convert_from_extras'),tk.get_validator('ignore_missing')]
        })
        schema.update({
            'scenario_id': [tk.get_converter('convert_from_extras'),tk.get_validator('ignore_missing')]
        })
        schema.update({
            'reliability_source': [tk.get_converter('convert_from_extras'),tk.get_validator('ignore_missing')]
        })
        schema.update({
            'application_id': [tk.get_converter('convert_from_extras'),tk.get_validator('ignore_missing')]
        })
        schema.update({
            'ex_license': [tk.get_converter('convert_from_extras'),tk.get_validator('ignore_missing')]
        })
        return schema

    def is_fallback(self):
        return True

    def package_types(self):
        return []

    def update_config(self, config):
        tk.add_template_directory(config, 'templates')
