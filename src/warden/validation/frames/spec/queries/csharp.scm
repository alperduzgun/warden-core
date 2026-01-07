; C# tree-sitter queries for ASP.NET Core API contract extraction
; Used by AspNetCoreExtractor for precise AST-based extraction

; ============================================
; Controller and Route Attributes
; ============================================

; [ApiController]
(attribute
  name: (identifier) @attr_name
  (#match? @attr_name "^(ApiController|Route|HttpGet|HttpPost|HttpPut|HttpPatch|HttpDelete)$")
  (attribute_argument_list
    (attribute_argument
      (string_literal) @route_path
    )?
  )?
) @controller_attr

; [Route("api/[controller]")]
(attribute
  name: (identifier) @route_attr
  (#eq? @route_attr "Route")
  (attribute_argument_list
    (attribute_argument
      (string_literal) @route_template
    )
  )
) @route_definition

; ============================================
; Controller Class
; ============================================

; public class UsersController : ControllerBase
(class_declaration
  (modifier) @visibility
  (#eq? @visibility "public")
  name: (identifier) @controller_name
  (base_list
    (simple_base_type
      (identifier) @base_type
      (#match? @base_type "^(Controller|ControllerBase)$")
    )
  )
  body: (declaration_list) @controller_body
) @controller_class

; ============================================
; Action Methods
; ============================================

; public async Task<ActionResult<User>> GetUser(int id)
(method_declaration
  (modifier) @method_visibility
  (#eq? @method_visibility "public")
  returns: (_) @return_type
  name: (identifier) @method_name
  parameters: (parameter_list) @params
  body: (_) @method_body
) @action_method

; ============================================
; Parameter Attributes
; ============================================

; [FromBody] CreateUserDto dto
(parameter
  (attribute_list
    (attribute
      name: (identifier) @param_attr
      (#match? @param_attr "^(FromBody|FromQuery|FromRoute|FromHeader)$")
    )
  )?
  type: (_) @param_type
  name: (identifier) @param_name
) @action_param

; ============================================
; DTO/Model Classes
; ============================================

; public class UserDto { ... }
; public record CreateUserRequest(...);
(class_declaration
  (modifier) @class_visibility
  (#eq? @class_visibility "public")
  name: (identifier) @model_name
  body: (declaration_list) @model_body
) @model_class

(record_declaration
  (modifier) @record_visibility
  (#eq? @record_visibility "public")
  name: (identifier) @record_name
  (parameter_list)? @record_params
) @record_model

; ============================================
; Properties
; ============================================

; public string Name { get; set; }
(property_declaration
  (modifier) @prop_visibility
  (#eq? @prop_visibility "public")
  type: (_) @prop_type
  name: (identifier) @prop_name
  (accessor_list) @accessors
) @property_def

; ============================================
; Enums
; ============================================

; public enum Status { Active, Inactive }
(enum_declaration
  (modifier) @enum_visibility
  (#eq? @enum_visibility "public")
  name: (identifier) @enum_name
  body: (enum_member_declaration_list
    (enum_member_declaration
      name: (identifier) @enum_value
    )*
  )
) @enum_def
