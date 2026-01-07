; Java tree-sitter queries for Spring Boot API contract extraction
; Used by SpringBootExtractor for precise AST-based extraction

; ============================================
; Controller Annotations
; ============================================

; @RestController
(marker_annotation
  name: (identifier) @annotation_name
  (#match? @annotation_name "^(RestController|Controller)$")
) @controller_annotation

; @RequestMapping("/api/users")
(annotation
  name: (identifier) @mapping_name
  (#match? @mapping_name "^(RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)$")
  arguments: (annotation_argument_list
    (element_value_pair
      key: (identifier) @key
      value: (string_literal) @path_value
    )?
    (string_literal)? @direct_path
  )?
) @mapping_annotation

; ============================================
; Controller Class
; ============================================

; public class UsersController
(class_declaration
  (modifiers
    (marker_annotation)* @class_annotations
    (modifier) @visibility
  )
  name: (identifier) @class_name
  body: (class_body) @class_body
) @controller_class

; ============================================
; Handler Methods
; ============================================

; public ResponseEntity<User> getUser(@PathVariable Long id)
(method_declaration
  (modifiers
    (annotation)* @method_annotations
    (modifier) @method_visibility
  )
  type: (_) @return_type
  name: (identifier) @method_name
  parameters: (formal_parameters) @params
  body: (block)? @method_body
) @handler_method

; ============================================
; Parameter Annotations
; ============================================

; @RequestBody CreateUserRequest request
; @PathVariable Long id
; @RequestParam String name
(formal_parameter
  (modifiers
    (annotation
      name: (identifier) @param_annotation
      (#match? @param_annotation "^(RequestBody|PathVariable|RequestParam|RequestHeader)$")
    )?
  )?
  type: (_) @param_type
  name: (identifier) @param_name
) @annotated_param

; ============================================
; DTO Classes
; ============================================

; public class UserDto { ... }
(class_declaration
  (modifiers
    (modifier) @dto_visibility
    (#eq? @dto_visibility "public")
  )
  name: (identifier) @dto_name
  body: (class_body
    (field_declaration
      (modifiers
        (modifier) @field_visibility
      )
      type: (_) @field_type
      declarator: (variable_declarator
        name: (identifier) @field_name
      )
    )*
  )
) @dto_class

; ============================================
; Record Classes (Java 16+)
; ============================================

; public record UserDto(String name, String email)
(record_declaration
  (modifiers
    (modifier) @record_visibility
  )
  name: (identifier) @record_name
  parameters: (formal_parameters
    (formal_parameter
      type: (_) @component_type
      name: (identifier) @component_name
    )*
  )
) @record_class

; ============================================
; Enums
; ============================================

; public enum Status { ACTIVE, INACTIVE }
(enum_declaration
  (modifiers
    (modifier) @enum_visibility
  )
  name: (identifier) @enum_name
  body: (enum_body
    (enum_constant
      name: (identifier) @enum_value
    )*
  )
) @enum_def

; ============================================
; Imports (for type resolution)
; ============================================

; import org.springframework.web.bind.annotation.*;
(import_declaration
  (scoped_identifier) @import_path
) @import_stmt
